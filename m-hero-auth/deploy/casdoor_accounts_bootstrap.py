#!/usr/bin/env python3
"""One-time (idempotent) Casdoor preparation for the 「账号管理」 feature. Needs a Casdoor GLOBAL admin credential only for
this run (the built-in application's client id/secret, read from a 600 file — never from argv, never printed).

  python3 casdoor_accounts_bootstrap.py --base http://127.0.0.1:8000 --org mhero \
      --bootstrap-cred /path/builtin-app.json   --out /home/ubuntu/m-hero-run/accounts-admin.cred \
      [--grant-all-apps alice,shared-admin] [--dry-run]

It (1) creates the role set mhero-app-{report,nss,accident,vip,district,cleaner,hub} (+ mhero-admin / mhero-supervisor if missing),
(2) creates org-admin user `svc-accounts` (isAdmin ONLY inside org mhero, no mhero-* roles, random machine password) and the
application `mhero-account-admin` (password grant only, no redirect URIs, sign-up off), (3) writes the credential JSON (mode 600)
used by the hub as MHERO_ADMIN_CRED_FILE, (4) optionally gives the listed accounts every mhero-app-* role.
The bootstrap-cred file is JSON {"client_id","client_secret"} of Casdoor's built-in app (`app-built-in`).
"""
import argparse, base64, json, os, secrets, string, sys, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from mhero_auth.casdoor_admin import CasdoorAdmin, load_credential  # noqa: E402
from mhero_auth.core import APP_IDS  # noqa: E402

SVC_USER, SVC_APP = "svc-accounts", "mhero-account-admin"


def api(base, auth, method, path, query=None, body=None):
    url = base + path + (("?" + urllib.parse.urlencode(query)) if query else "")
    h = {"Authorization": "Basic " + base64.b64encode(f"{auth['client_id']}:{auth['client_secret']}".encode()).decode()}
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def rand(n=40):
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--org", default="mhero")
    ap.add_argument("--bootstrap-cred", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--template-app", default="admin/mhero-sso"); ap.add_argument("--grant-all-apps", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    base, org = a.base.rstrip("/"), a.org
    boot = load_credential_min(a.bootstrap_cred)
    plan = []
    users = {u["name"]: u for u in api(base, boot, "GET", "/api/get-users", {"owner": org}).get("data") or []}
    apps = {x["name"] for x in api(base, boot, "GET", "/api/get-applications", {"owner": "admin"}).get("data") or []}
    have_cred = os.path.exists(a.out)
    plan.append(f"roles: ensure {len(APP_IDS)} app roles + admin/supervisor in org {org}")
    plan.append(f"user {org}/{SVC_USER}: {'exists' if SVC_USER in users else 'create (org admin, no mhero roles)'}")
    plan.append(f"application admin/{SVC_APP}: {'exists' if SVC_APP in apps else 'create (password grant only)'}")
    plan.append(f"credential file {a.out}: {'keep' if have_cred and SVC_USER in users and SVC_APP in apps else 'write (mode 600)'}")
    grant = [x.strip() for x in a.grant_all_apps.split(",") if x.strip()]
    if grant:
        plan.append("grant all app roles to: " + ", ".join(grant))
    print("\n".join(plan))
    if a.dry_run:
        print("(dry run: nothing changed)")
        return 0
    cred = None
    if SVC_APP not in apps:
        tpl = api(base, boot, "GET", "/api/get-application", {"id": a.template_app})["data"]
        cid, csec = rand(20), rand(40)
        tpl.update({"name": SVC_APP, "displayName": "mhero 账号管理（服务端）", "clientId": cid, "clientSecret": csec, "grantTypes": ["password"],
                    "redirectUris": [], "enableSignUp": False, "organization": org})
        tpl.pop("createdTime", None)
        r = api(base, boot, "POST", "/api/add-application", body=tpl)
        assert r.get("status") == "ok", r.get("msg")
        cred = {"client_id": cid, "client_secret": csec}
    pw = rand(40) + "aA1"
    if SVC_USER not in users:
        r = api(base, boot, "POST", "/api/add-user", body={"owner": org, "name": SVC_USER, "displayName": "账号管理服务", "password": pw, "isAdmin": True,
                                                         "type": "normal-user", "signupApplication": "mhero-sso", "email": ""})
        assert r.get("status") == "ok", r.get("msg")
    elif cred is not None or not have_cred:
        u = users[SVC_USER]
        # reset the machine password through update-user (hash is recomputed server side)
        u["password"] = pw
        r = api(base, boot, "POST", "/api/update-user", {"id": f"{org}/{SVC_USER}", "columns": "password"}, u)
        assert r.get("status") == "ok", r.get("msg")
    if cred is None and not have_cred:
        app_ = api(base, boot, "GET", "/api/get-application", {"id": f"admin/{SVC_APP}"})["data"]
        cred = {"client_id": app_["clientId"], "client_secret": app_["clientSecret"]}
    if cred is not None:
        cred.update({"username": SVC_USER, "password": pw})
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(cred, f)
        os.chmod(a.out, 0o600)
    cl = CasdoorAdmin(base, org, load_credential(a.out))
    made = cl.ensure_roles()
    print("roles created:", ", ".join(made) or "none (all present)")
    for u in grant:
        for app_id in APP_IDS:
            cl.set_membership(f"mhero-app-{app_id}", u, True)
        print("granted all app roles to", u)
    print("OK")
    return 0


def load_credential_min(path):
    import stat
    st = os.stat(path)
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SystemExit(f"{path} must be chmod 600")
    d = json.load(open(path))
    assert d.get("client_id") and d.get("client_secret")
    return d


if __name__ == "__main__":
    raise SystemExit(main())
