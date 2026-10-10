"""Real Casdoor (throwaway dev instance on :18100 prepared by deploy/casdoor_accounts_bootstrap.py): admin API client,
org scoping, forced password change at first login, per-system role -> ID-token claim -> mhero_auth access decision."""
import json, os, time, urllib.parse as up
import pytest, requests

D = os.environ.get("CASDOOR_DEV3_DIR", "/workspace/casdoor-dev3")
B = "http://127.0.0.1:18100"
CRED = f"{D}/accounts-admin.cred"
try:
    requests.get(B + "/.well-known/openid-configuration", timeout=2).raise_for_status()
    S = json.load(open("/workspace/casdoor-dev/secrets.json"))
    assert os.path.exists(CRED)
except Exception:
    pytest.skip("no throwaway Casdoor / credential", allow_module_level=True)

from mhero_auth.accounts import AccountError, AccountService
from mhero_auth.casdoor_admin import CasdoorAdmin, CasdoorError, load_credential
from mhero_auth.core import AuthConfig, Authenticator, Request


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    d = tmp_path_factory.mktemp("acct")
    return AccountService(CasdoorAdmin(B, "mhero", load_credential(CRED)), audit_path=str(d / "a.log"), revoke_path=str(d / "r.json"))


def login_code(user, pw, redirect="http://127.0.0.1:19002/_auth/callback", extra=None):
    q = {"clientId": S["client_id"], "responseType": "code", "redirectUri": redirect, "scope": "openid profile email", "state": "st", "nonce": "n1"}
    return requests.post(f"{B}/api/login", params=q, json={"application": "mhero-sso", "organization": "mhero", "username": user, "password": pw, "type": "code"}).json()


def test_credential_file_must_be_private(tmp_path):
    p = tmp_path / "c.json"; p.write_text(open(CRED).read()); os.chmod(p, 0o644)
    with pytest.raises(CasdoorError, match="chmod 600"):
        load_credential(str(p))


def test_admin_credential_cannot_touch_other_orgs():
    c = CasdoorAdmin(B, "mhero", load_credential(CRED))
    with pytest.raises(CasdoorError, match="Unauthorized"):
        c._api("GET", "/api/get-users", query={"owner": "built-in"})
    with pytest.raises(CasdoorError):
        c._uid("built-in/admin")           # client also refuses slashes in names


def test_create_forced_password_change_and_app_access(svc):
    n = "it" + str(int(time.time() * 1000))[-8:]
    svc.create("alice", n, "集成测试", "Initial-Passw0rd-A", "supervisor", ["report"])
    r = login_code(n, "Initial-Passw0rd-A")
    assert r["data"] == "RequiredUpdatePassword"                       # cannot get a code until the user changes the password
    # user changes it themselves (Casdoor self-service), then logs in
    chg = requests.post(f"{B}/api/set-password", data={"userOwner": "mhero", "userName": n, "oldPassword": "Initial-Passw0rd-A", "newPassword": "Chosen-By-User-9z"},
                        headers={"Authorization": "Basic " + __import__("base64").b64encode(f"{S['client_id']}:{S['client_secret']}".encode()).decode()}).json()
    assert chg["status"] == "ok", chg
    me = next(r for r in svc.snapshot() if r["name"] == n)
    assert me["level"] == "supervisor" and me["apps"] == ["report"]
    # roles -> ID token -> access decision, flag ON
    env = {"MHERO_AUTH": "on", "MHERO_AUTH_ISSUER": B, "MHERO_AUTH_CLIENT_ID": S["client_id"], "MHERO_AUTH_CLIENT_SECRET": S["client_secret"],
           "MHERO_AUTH_BASE_URL": "http://127.0.0.1:19002", "MHERO_AUTH_SESSION_SECRET": "z" * 48, "MHERO_AUTH_ORG": "mhero", "MHERO_AUTH_REQUIRE_APP": "1"}

    def enter(app_name):
        a = Authenticator(AuthConfig.from_env(app_name, env=env))
        d = a._login(Request("GET", "/_auth/login", {}, {}, {"next": "/"}))
        q = dict(up.parse_qsl(up.urlparse(d.location).query))
        stc = d.set_cookies[0].split(";")[0].split("=", 1)
        rr = requests.post(f"{B}/api/login", params={"clientId": q["client_id"], "responseType": "code", "redirectUri": q["redirect_uri"], "scope": q["scope"],
                           "state": q["state"], "nonce": q["nonce"]}, json={"application": "mhero-sso", "organization": "mhero", "username": n,
                                                                              "password": "Chosen-By-User-9z", "type": "code"}).json()
        assert rr["status"] == "ok", rr
        return a._callback(Request("GET", "/_auth/callback", {}, {stc[0]: stc[1]}, {"code": rr["data"], "state": q["state"]}))
    assert enter("reportdb").kind == "redirect"
    assert enter("nss").status == 403
    svc.set_apps("alice", n, ["nss"])
    assert enter("nss").kind == "redirect" and enter("reportdb").status == 403
    svc.set_disabled("alice", n, True)
    assert login_code(n, "Chosen-By-User-9z")["status"] == "error"        # disabled accounts cannot log in at all
    svc.set_disabled("alice", n, False)
    assert enter("nss").kind == "redirect"
    svc.reset_password("alice", n, "Reset-By-Admin-7q")
    assert login_code(n, "Reset-By-Admin-7q")["data"] == "RequiredUpdatePassword"
