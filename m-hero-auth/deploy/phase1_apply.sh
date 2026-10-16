#!/bin/bash
# Phase 1 rollout helper — run ON dfms as ubuntu. NOTHING here is executed automatically.
#   phase1_apply.sh prep                 one-time: install m-hero-auth into venvs, create auth.env (all apps OFF), hook run_prod.sh
#   phase1_apply.sh app <hub|vip|district|cleaner|nss> [audit|on|off]   patch + restart ONE app, set its mode (default audit)
#   phase1_apply.sh mode <app> <audit|on|off>      change mode only (restarts that app)
#   phase1_apply.sh rollback <app>       mode=off + restore the pre-patch file
#   phase1_apply.sh status
# Break-glass without restart:  touch ~/m-hero-run/auth-off.flag   (all apps; remove file to re-enable)
set -euo pipefail
R=$HOME/m-hero-run; P=$HOME/m-hero-prod; SC="supervisorctl -c $R/supervisor/supervisord.conf"
ENVF=$R/auth.env; PK=$P/m-hero-auth
declare -A PROG=([hub]=hub-web [vip]=vip-web [district]=district-web [cleaner]=cleaner-web [nss]=nss-web)
declare -A VENV=([hub]=m-hero-hub [vip]=m-hero-vip-custom-alert [district]=mhero_district_form [cleaner]=store-timeout-cleaner [nss]=NSS_Questionnaire_Reminder)
declare -A HOST=([hub]=oa-m-hero [vip]=m-hero-vip-alert [district]=m-hero-district-form [cleaner]=store-timeout-cleaner [nss]=m-hero-nss-questionnaire)
declare -A PATCH=([hub]="hub-sso hub-userbar" [vip]="vip-sso vip-watchdog-token" [district]="district-sso district-latest-report" [cleaner]=cleaner-sso [nss]=nss-sso)
PATCHDIR=$PK/patches

prep() {
  [ -d "$PK" ] || { echo "copy m-hero-auth to $PK first (rsync)"; exit 1; }
  for a in "${!VENV[@]}"; do
    VPY=$R/venvs/${VENV[$a]}/bin/python
    # dfms has no uv and the venvs have no pip: use system pip3 (--python) for cryptography, and a .pth for the in-repo package
    pip3 --python $VPY install -q cryptography
    SP=$($VPY -c "import sysconfig;print(sysconfig.get_paths()['purelib'])"); echo "$PK" > $SP/mhero_auth.pth
    $R/venvs/${VENV[$a]}/bin/python -c "import mhero_auth,cryptography;print('${VENV[$a]}: mhero_auth', mhero_auth.__version__)"
  done
  if [ ! -f "$ENVF" ]; then
    umask 077
    python3 - <<'PY'
import os, secrets
R=os.path.expanduser("~/m-hero-run")
c=dict(l.strip().split("=",1) for l in open(R+"/casdoor-client.env") if "=" in l)
tok=secrets.token_urlsafe(32)
open(R+"/watchdog.token","w").write(tok+"\n"); os.chmod(R+"/watchdog.token",0o600)
hosts={"hub":"oa-m-hero","vip":"m-hero-vip-alert","district":"m-hero-district-form","cleaner":"store-timeout-cleaner","nss":"m-hero-nss-questionnaire"}
L=["# m-hero SSO (Casdoor) — generated; 600. mode per app: off|audit|on",
   "export MHERO_AUTH_ISSUER=https://sso-m-hero.41box.com","export MHERO_AUTH_INTERNAL_ISSUER=http://127.0.0.1:8000",
   f"export MHERO_AUTH_CLIENT_ID={c['MHERO_AUTH_CLIENT_ID']}",f"export MHERO_AUTH_CLIENT_SECRET={c['MHERO_AUTH_CLIENT_SECRET']}",
   "export MHERO_AUTH_ORG=mhero","export MHERO_AUTH_SESSION_HOURS=720","export MHERO_AUTH_REVALIDATE_HOURS=12",
   "export MHERO_AUTH_OFF_FILE="+R+"/auth-off.flag",
   f"export MHERO_AUTH_VIP_SERVICE_TOKENS=watchdog:supervisor:{tok}","export WATCHDOG_AUTH_TOKEN_FILE="+R+"/watchdog.token"]
for a,h in hosts.items():
    U=a.upper()
    L+= [f"export MHERO_AUTH_{U}=off", f"export MHERO_AUTH_{U}_BASE_URL=https://{h}.41box.com", f"export MHERO_AUTH_{U}_SESSION_SECRET={secrets.token_hex(32)}"]
open(R+"/auth.env","w").write("\n".join(L)+"\n")
PY
    echo "created $ENVF (600), all apps OFF"
  fi
  grep -q auth.env $R/launchers/run_prod.sh || {
    cp $R/launchers/run_prod.sh $R/launchers/run_prod.sh.bak-pre-sso
    sed -i '/^source \/home\/ubuntu\/m-hero-run\/launchers\/prod_env.sh/a [[ -f /home/ubuntu/m-hero-run/auth.env ]] \&\& source /home/ubuntu/m-hero-run/auth.env' $R/launchers/run_prod.sh
    echo "hooked auth.env into run_prod.sh (backup: run_prod.sh.bak-pre-sso)"; }
}
setmode() { sed -i "s/^export MHERO_AUTH_${1^^}=.*/export MHERO_AUTH_${1^^}=$2/" $ENVF; }
restart() { $SC restart ${PROG[$1]}; [ "$1" = vip ] && $SC restart vip-watchdog || true; }
apply() {
  local a=$1 m=${2:-audit}; cd $P
  for p in ${PATCH[$a]}; do
    if patch -p1 --dry-run -s -R < $PATCHDIR/$p.patch >/dev/null 2>&1; then echo "$p already applied"; continue; fi
    patch -p1 --dry-run < $PATCHDIR/$p.patch >/dev/null || { echo "PATCH $p does not apply cleanly -> abort"; exit 1; }
    patch -p1 -b -z .pre-sso < $PATCHDIR/$p.patch
  done
  setmode $a $m; restart $a; sleep 4
}
declare -A PORT=([hub]=9004 [vip]=9002 [district]=9003 [cleaner]=5001 [nss]=9005)
case "${1:-}" in
  prep) prep ;;
  app) apply "$2" "${3:-audit}"; curl -s -o /dev/null -w "$2 local / -> %{http_code}\n" http://127.0.0.1:${PORT[$2]}/ ;;
  mode) setmode "$2" "$3"; restart "$2" ;;
  rollback) setmode "$2" off; restart "$2"; cd $P
    for p in ${PATCH[$2]}; do patch -p1 -R -s < $PATCHDIR/$p.patch || echo "(patch $p: manual restore from *.pre-sso)"; done; restart "$2" ;;
  status) grep -E "^export MHERO_AUTH_[A-Z]+=(off|audit|on)$" $ENVF; ls $R/auth-off.flag 2>/dev/null && echo "BREAK-GLASS FLAG PRESENT (auth disabled)"; $SC status | grep -E "web|watchdog" ;;
  *) sed -n 2,10p "$0" ;;
esac
