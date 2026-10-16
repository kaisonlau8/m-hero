import json, os, time
import pytest
from fakes import FakeCasdoor
from mhero_auth.accounts import AccountError, AccountService
from mhero_auth.core import AuthConfig, Authenticator
from test_core import R, login, mk, sess_cookie

PW = "Abcdef12345"


@pytest.fixture
def svc(tmp_path):
    f = FakeCasdoor()
    f.seed("alice", "admin"); f.seed("bob", "supervisor", ["report"]); f.seed("carol", "admin")
    f.seed("svc-accounts", "admin")           # the service account must be invisible and untouchable
    return AccountService(f, audit_path=str(tmp_path / "audit.log"), revoke_path=str(tmp_path / "revoke.json"), secret="x" * 32)


def test_snapshot_hides_service_account_and_shows_levels(svc):
    rows = {r["name"]: r for r in svc.snapshot()}
    assert "svc-accounts" not in rows
    assert rows["alice"]["level"] == "admin" and rows["bob"]["level"] == "supervisor" and rows["bob"]["apps"] == ["report"]
    with pytest.raises(AccountError):
        svc.set_disabled("alice", "svc-accounts", True)


def test_create_requires_admin_typed_strong_password_and_forces_change(svc):
    for bad in ("short1A", "alllowercase123", "ALLUPPERCASE123", "NoDigitsHereAbc", "Bobsmith12345"):
        with pytest.raises(AccountError):
            svc.create("alice", "bobsmith", "B", bad, "supervisor", [])
    svc.create("alice", "dave", "戴维", PW + "x", "supervisor", ["report", "nss"])
    u = svc.c.get_user("dave")
    assert u["needUpdatePassword"] is True            # first login forces a password change
    r = {x["name"]: x for x in svc.snapshot()}["dave"]
    assert r["level"] == "supervisor" and r["apps"] == ["report", "nss"] or r["apps"] == ["report", "nss"]
    with pytest.raises(AccountError):
        svc.create("alice", "dave", "x", PW, "supervisor", [])        # duplicate
    for bad_name in ("Admin", "ab", "svc-accounts", "1abc", "a b c"):
        with pytest.raises(AccountError):
            svc.create("alice", bad_name, "x", PW, "supervisor", [])
    with pytest.raises(AccountError):
        svc.create("alice", "erin", "x", PW, "root", [])
    with pytest.raises(AccountError):
        svc.create("alice", "erin", "x", PW, "supervisor", ["nope"])


def test_password_never_in_audit_log(svc):
    svc.create("alice", "dave", "D", "Sup3rSecretPw!x", "supervisor", [])
    svc.reset_password("alice", "dave", "An0therSecretPw!")
    text = open(svc.audit_path).read()
    assert "Sup3rSecretPw" not in text and "An0therSecretPw" not in text
    assert [json.loads(l)["action"] for l in text.splitlines()] == ["create", "reset_password"]
    assert oct(os.stat(svc.audit_path).st_mode & 0o777) == "0o600"
    assert svc.c.get_user("dave")["needUpdatePassword"] is True


def test_reset_password_forces_change_and_logout(svc):
    svc.c.users["bob"]["needUpdatePassword"] = False
    svc.reset_password("alice", "bob", "NewPassw0rd!!")
    assert svc.c.users["bob"]["needUpdatePassword"] is True
    assert json.load(open(svc.revoke_path))["bob"] > 0
    with pytest.raises(AccountError):
        svc.reset_password("alice", "bob", "weak")


def test_cannot_demote_or_disable_self(svc):
    with pytest.raises(AccountError, match="自己"):
        svc.set_level("alice", "alice", "supervisor")
    with pytest.raises(AccountError, match="自己"):
        svc.set_disabled("alice", "alice", True)
    assert svc.c.users["alice"]["isForbidden"] is False
    assert [json.loads(l)["ok"] for l in open(svc.audit_path)] == [False, False]      # denied attempts are audited too


def test_cannot_remove_last_admin(svc):
    svc.set_level("alice", "carol", "supervisor")              # alice remains
    with pytest.raises(AccountError, match="最后"):
        svc.set_level("bob_nonadmin_actor", "alice", "supervisor")
    with pytest.raises(AccountError, match="最后"):
        svc.set_disabled("someone", "alice", True)
    svc.c.seed("zed", "admin", disabled=True)                    # a disabled admin does not count as an active admin
    with pytest.raises(AccountError, match="最后"):
        svc.set_disabled("someone", "alice", True)
    svc.c.users["zed"]["isForbidden"] = False
    svc.set_disabled("someone", "alice", True)                 # now zed is a second active admin


def test_level_is_exclusive_and_app_roles_roundtrip(svc):
    svc.set_level("alice", "bob", "admin")
    assert "bob" in svc.c.roles["mhero-admin"] and "bob" not in svc.c.roles["mhero-supervisor"]
    svc.set_apps("alice", "bob", ["vip", "hub"])
    assert {a for a in ("report", "vip", "hub") if "bob" in svc.c.roles.get(f"mhero-app-{a}", set())} == {"vip", "hub"}


def test_changes_force_logout(svc):
    for fn in (lambda: svc.set_apps("alice", "bob", []), lambda: svc.set_level("alice", "bob", "admin"), lambda: svc.set_disabled("alice", "bob", True)):
        if os.path.exists(svc.revoke_path):
            os.remove(svc.revoke_path)
        fn()
        assert "bob" in json.load(open(svc.revoke_path))


def test_confirmation_token_binds_actor_action_params_and_expires(svc):
    p = {"name": "bob", "level": "admin", "apps": []}
    t = svc.make_token("alice", "set_level", p)
    assert svc.check_token(t, "alice", "set_level", p)
    assert not svc.check_token(t, "carol", "set_level", p)
    assert not svc.check_token(t, "alice", "set_apps", p)
    assert not svc.check_token(t, "alice", "set_level", {**p, "name": "alice"})
    assert not svc.check_token("garbage", "alice", "set_level", p)
    svc.clock = lambda: time.time() + 400
    assert not svc.check_token(t, "alice", "set_level", p)


# ---------------------------------------------------------------- per-system access in the auth core
def app_env(env, **kw):
    return {**env, "MHERO_AUTH_REQUIRE_APP": "1", **kw}


def test_default_off_ignores_app_roles(env, oidc):
    a = mk(env, "vip")
    c = sess_cookie(a, login(a, oidc, {"roles": [{"name": "mhero-supervisor"}]}))     # no mhero-app-vip
    assert a.authorize(R(path="/x", cookies=c)).kind == "allow"


def test_require_app_denies_without_role_but_global_admin_passes(env, oidc):
    a = mk(app_env(env), "vip")
    cb = login(a, oidc, {"roles": [{"name": "mhero-supervisor"}, {"name": "mhero-app-report"}]})
    assert cb.kind == "deny" and cb.status == 403 and not any(c.startswith("mh_vip=") and "Max-Age=0" not in c for c in cb.set_cookies)
    cb = login(a, oidc, {"roles": [{"name": "mhero-supervisor"}, {"name": "mhero-app-vip"}]})
    assert cb.kind == "redirect"
    c = sess_cookie(a, cb)
    assert a.authorize(R(path="/x", cookies=c)).kind == "allow"
    cb = login(a, oidc, {"roles": [{"name": "mhero-admin"}]})                         # global admin: no app roles needed
    assert cb.kind == "redirect" and a.authorize(R(path="/x", cookies=sess_cookie(a, cb))).kind == "allow"


def test_app_role_is_per_system_reportdb_alias(env, oidc):
    a = mk(app_env(env), "reportdb")
    cb = login(a, oidc, {"roles": [{"name": "mhero-supervisor"}, {"name": "mhero-app-report"}]})
    assert cb.kind == "redirect"
    a2 = mk(app_env(env), "nss")
    assert login(a2, oidc, {"roles": [{"name": "mhero-supervisor"}, {"name": "mhero-app-report"}]}).status == 403


def test_hub_home_open_to_any_account_with_a_system_but_not_to_zero_systems(env, oidc):
    a = mk(app_env(env), "hub")
    cb = login(a, oidc, {"roles": [{"name": "mhero-supervisor"}, {"name": "mhero-app-report"}]})     # report-only supervisor reaches the 黄页
    assert cb.kind == "redirect"
    assert a.authorize(R(path="/", cookies=sess_cookie(a, cb))).kind == "allow"
    assert login(a, oidc, {"roles": [{"name": "mhero-supervisor"}]}).status == 403                     # no system at all -> still refused


def test_old_cookie_without_apps_is_sent_through_login_not_denied(env, oidc):
    a_old = mk(env, "vip")
    c = sess_cookie(a_old, login(a_old, oidc, {"roles": [{"name": "mhero-supervisor"}]}))
    old = a_old._unsign(c["mh_vip"]); old.pop("ap"); old.pop("ga"); old.pop("iat")
    c = {"mh_vip": a_old._sign(old)}
    a = mk(app_env(env), "vip")
    d = a.authorize(R(path="/x", cookies=c))
    assert d.kind == "redirect" and d.location.startswith("/_auth/login")          # lockout protection: re-login, not 403
    d = a.authorize(R(path="/api/x", cookies=c))
    assert d.status == 401


def test_session_denied_when_flag_on_and_apps_missing_in_new_cookie(env, oidc):
    a_off = mk(env, "vip")
    c = sess_cookie(a_off, login(a_off, oidc, {"roles": [{"name": "mhero-supervisor"}]}))     # new-style cookie, apps=[]
    a = mk(app_env(env), "vip")
    assert a.authorize(R(path="/x", cookies=c)).status == 403


def test_audit_mode_logs_but_never_blocks(env, oidc, caplog):
    a = mk(app_env(env, MHERO_AUTH="audit"), "vip")
    cb = login(a, oidc, {"roles": [{"name": "mhero-supervisor"}]})
    assert cb.kind == "redirect"
    assert a.authorize(R(path="/x", cookies=sess_cookie(a, cb))).kind == "allow"


def test_service_token_and_break_glass_unaffected(env, oidc, tmp_path):
    flag = tmp_path / "off.flag"
    a = mk(app_env(env, MHERO_AUTH_OFF_FILE=str(flag), MHERO_AUTH_SERVICE_TOKENS="watchdog:supervisor:" + "t" * 24), "vip")
    assert a.authorize(R(path="/api/vip/status", headers={"X-MHero-Token": "t" * 24})).kind == "allow"
    assert a.authorize(R(path="/x")).kind == "redirect"
    flag.write_text("1")
    assert a.authorize(R(path="/x")).kind == "allow"


def test_force_logout_revoke_file(env, oidc, tmp_path):
    rv = tmp_path / "rv.json"
    a = mk(app_env(env, MHERO_AUTH_REVOKE_FILE=str(rv)), "vip")
    cb = login(a, oidc, {"roles": [{"name": "mhero-admin"}], "name": "alice"})
    c = sess_cookie(a, cb)
    assert a.authorize(R(path="/x", cookies=c)).kind == "allow"
    rv.write_text(json.dumps({"alice": time.time() + 5}))
    d = a.authorize(R(path="/x", cookies=c))
    assert d.kind == "redirect" and d.location.startswith("/_auth/login")
    rv.write_text(json.dumps({"someone-else": time.time() + 5}))
    assert a.authorize(R(path="/x", cookies=c)).kind == "allow"
    rv.write_text(json.dumps({"*": time.time() + 5}))
    assert a.authorize(R(path="/x", cookies=c)).kind == "redirect"
    rv.write_text("not json")                                   # corrupt file must not lock everyone out
    assert a.authorize(R(path="/x", cookies=c)).kind == "allow"
