set -euo pipefail
R=$HOME/m-hero-run; C=$R/casdoor; D=$R/data/casdoor
mkdir -p $C $D $R/logs $R/data/casdoor-backup; chmod 700 $D $R/data/casdoor-backup
if [ ! -x $C/casdoor ]; then tar xzf $HOME/casdoor-dl/c.tgz -C $C; fi
umask 077
python3 - <<'PY'
import secrets, json, os
R=os.path.expanduser("~/m-hero-run"); C=R+"/casdoor"; D=R+"/data/casdoor"
def w(p,s,m=0o600):
    open(p,"w").write(s); os.chmod(p,m)
if not os.path.exists(R+"/casdoor-admin.secret"):
    w(R+"/casdoor-admin.secret", secrets.token_urlsafe(24)+"\n")
if not os.path.exists(R+"/casdoor-client.env"):
    cid, cs = secrets.token_hex(10), secrets.token_hex(20)
    w(R+"/casdoor-client.env", f"MHERO_AUTH_CLIENT_ID={cid}\nMHERO_AUTH_CLIENT_SECRET={cs}\n")
env = dict(l.strip().split("=",1) for l in open(R+"/casdoor-client.env") if "=" in l)
hosts = ["oa-m-hero","m-hero-report","store-timeout-cleaner","m-hero-district-form","m-hero-vip-alert","m-hero-nss-questionnaire"]
app = {"owner":"admin","name":"mhero-sso","displayName":"猛士科技 统一登录","organization":"mhero","enablePassword":True,"enableSignUp":False,
 "enableCodeSignin":False,"clientId":env["MHERO_AUTH_CLIENT_ID"],"clientSecret":env["MHERO_AUTH_CLIENT_SECRET"],
 "redirectUris":[f"https://{h}.41box.com/_auth/callback" for h in hosts],"grantTypes":["authorization_code","refresh_token"],
 "tokenFormat":"JWT","expireInHours":720,"refreshExpireInHours":720,"cookieExpireInHours":720,"providers":[],"signupItems":[],
 "signinMethods":[{"name":"Password","displayName":"Password","rule":"All"}],"cert":"cert-built-in"}
org = {"owner":"admin","name":"mhero","displayName":"猛士科技","websiteUrl":"https://sso-m-hero.41box.com","passwordType":"bcrypt",
 "passwordOptions":["AtLeast8","Aa123"],"countryCodes":["CN"],"languages":["zh","en"],"defaultApplication":"mhero-sso","enableSoftDeletion":False}
roles=[{"owner":"mhero","name":n,"displayName":d,"users":[],"roles":[],"domains":[],"isEnabled":True} for n,d in (("mhero-admin","管理员"),("mhero-supervisor","督导"))]
init={"organizations":[org],"applications":[app],"users":[],"roles":roles,"permissions":[],"models":[],"adapters":[],"providers":[],"groups":[],"ldaps":[],"syncers":[],"webhooks":[],"tokens":[],"resources":[],"certs":[]}
w(C+"/init_data.json", json.dumps(init,indent=1,ensure_ascii=False))
w(C+"/conf/app.conf", f"""appname = casdoor
httpaddr = 127.0.0.1
httpport = 8000
runmode = prod
copyrequestbody = true
driverName = sqlite
dataSourceName = file:{D}/casdoor.db?cache=shared
dbName = casdoor
tableNamePrefix =
showSql = false
origin = https://sso-m-hero.41box.com
socks5Proxy = ""
staticBaseUrl = "https://cdn.casbin.org"
defaultApplication = "app-built-in"
enableGzip = true
ldapServerPort = 0
ldapsServerPort = 0
radiusServerPort = 0
logConfig = {{"adapter":"file", "filename": "{R}/logs/casdoor-app.log", "maxdays":30, "perm":"0640"}}
initDataNewOnly = true
initDataFile = "{C}/init_data.json"
""")
PY
chmod 700 $C
echo prepared
