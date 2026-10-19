"""四级角色 × 各系统（按生产配置）+ 系统单独角色覆盖 + 只读管理员进入全部系统 + 账号服务。"""
import json

import pytest

from mhero_auth.core import AuthConfig, Authenticator
from test_core import R, login, sess_cookie
from fakes import FakeCasdoor
from mhero_auth.accounts import AccountError, AccountService

# production-like per-system config (code + env), see each repo's init_app call and auth.env
SYSTEMS = {
    "nss": {},
    "vip": {"public_paths": ["/feishu/card"]},
    "district": {"user_get_paths": ["/api/report/latest"]},
    "cleaner": {"admin_paths": ["/admin/*", "/api/admin/*"], "supervisor_write_paths": ["/api/timeout/import"],
                "user_get_paths": ["/", "/theater/*", "/api/timeout/meta", "/api/timeout/chart"]},
    "hub": {"admin_paths": ["/admin/*"], "account_paths": ["/admin/accounts*"], "any_role_paths": ["/account/password"],
            "user_get_paths": ["/*"]},
}
LEVEL_CLAIM = {"admin": "mhero-admin", "readonly_admin": "mhero-readonly-admin", "supervisor": "mhero-supervisor", "user": None}


def cookie_for(env, oidc, app, level, overrides_file="", name="u1", **cfg):
    a = Authenticator(AuthConfig.from_env(app, env={**env, "MHERO_AUTH_ROLE_OVERRIDES_FILE": overrides_file}, **cfg))
    roles = [{"name": LEVEL_CLAIM[level]}] if LEVEL_CLAIM[level] else []
    roles += [{"name": f"mhero-app-{x}"} for x in ("nss", "vip", "district", "cleaner", "hub")]
    return a, sess_cookie(a, login(a, oidc, {"roles": roles, "name": name}))


def ok(a, c, method, path):
    h = {"Origin": a.cfg.base_url} if method != "GET" else {}
    d = a.authorize(R(method, path, cookies=c, headers=h))
    return d.kind == "allow"


# expected[role] = (GET page, GET summary-page, POST trigger, POST supervisor-submit, GET admin page, POST admin, GET accounts)
@pytest.mark.parametrize("level,exp", [
    ("admin",          dict(get=True,  summ=True, post=True,  sub=True,  aget=True,  apost=True,  acct=True)),
    ("readonly_admin", dict(get=True,  summ=True, post=False, sub=False, aget=True,  apost=False, acct=False)),
    ("supervisor",     dict(get=True,  summ=True, post=False, sub=True,  aget=False, apost=False, acct=False)),
    ("user",           dict(get=False, summ=True, post=False, sub=False, aget=False, apost=False, acct=False)),
])
@pytest.mark.parametrize("app", list(SYSTEMS))
def test_role_matrix_per_system(env, oidc, app, level, exp):
    a, c = cookie_for(env, oidc, app, level, **SYSTEMS[app])
    summary = {"district": "/api/report/latest", "cleaner": "/theater/东区", "hub": "/"}.get(app)
    detail = {"cleaner": "/group/abcdef123", "hub": "/"}.get(app, "/api/due")
    if app == "hub":                          # 黄页: everyone may open the cards page; only 账号管理 differs
        assert ok(a, c, "GET", "/") is True
        assert ok(a, c, "GET", "/admin/accounts") is exp["acct"]
        assert ok(a, c, "POST", "/admin/accounts/execute") is exp["acct"]
        assert ok(a, c, "POST", "/account/password") is True       # change own password: any role
        return
    assert ok(a, c, "GET", detail) is exp["get"]
    if summary:
        assert ok(a, c, "GET", summary) is exp["summ"]
    assert ok(a, c, "POST", "/api/run") is exp["post"]
    if app == "cleaner":
        assert ok(a, c, "POST", "/api/timeout/import") is exp["sub"]
        assert ok(a, c, "GET", "/admin/rules") is exp["aget"]
        assert ok(a, c, "POST", "/api/admin/recompute") is exp["apost"]


def test_per_system_override(env, oidc, tmp_path):
    ov = tmp_path / "ov.json"
    ov.write_text(json.dumps({"u1": {"nss": "admin", "cleaner": "readonly_admin", "vip": "user"}}))
    a, c = cookie_for(env, oidc, "nss", "supervisor", str(ov))
    assert ok(a, c, "POST", "/api/run")                          # per-system super admin in NSS
    a, c = cookie_for(env, oidc, "vip", "supervisor", str(ov))
    assert not ok(a, c, "GET", "/api/vip/status")                # lowered to 用户 in VIP
    a, c = cookie_for(env, oidc, "cleaner", "supervisor", str(ov), **SYSTEMS["cleaner"])
    assert ok(a, c, "GET", "/group/abcdef123") and not ok(a, c, "POST", "/api/timeout/import")
    a, c = cookie_for(env, oidc, "district", "supervisor", str(ov))
    assert not ok(a, c, "POST", "/api/run")                      # no override for district -> global 督导
    # per-system admin is NOT a global admin: no account management on the hub
    ov.write_text(json.dumps({"u1": {"hub": "admin"}}))
    a, c = cookie_for(env, oidc, "hub", "supervisor", str(ov), **SYSTEMS["hub"])
    assert not ok(a, c, "GET", "/admin/accounts")
    # a global super admin cannot be lowered
    ov.write_text(json.dumps({"boss": {"nss": "user"}}))
    a, c = cookie_for(env, oidc, "nss", "admin", str(ov), name="boss")
    assert ok(a, c, "POST", "/api/run")


def test_override_change_applies_without_relogin(env, oidc, tmp_path):
    ov = tmp_path / "ov.json"
    a, c = cookie_for(env, oidc, "nss", "supervisor", str(ov))
    assert not ok(a, c, "POST", "/api/run")
    ov.write_text(json.dumps({"u1": {"nss": "admin"}}))
    assert ok(a, c, "POST", "/api/run")


def test_readonly_admin_enters_every_system_without_app_roles(env, oidc):
    e = {**env, "MHERO_AUTH_REQUIRE_APP": "1"}
    a = Authenticator(AuthConfig.from_env("vip", env=e))
    c = sess_cookie(a, login(a, oidc, {"roles": [{"name": "mhero-readonly-admin"}]}))
    assert ok(a, c, "GET", "/api/vip/status") and not ok(a, c, "POST", "/api/vip/crawl")
    cb = login(a, oidc, {"roles": [{"name": "mhero-supervisor"}]})          # supervisor without mhero-app-vip
    assert cb.status == 403


# ---------------------------------------------------------------- account service
@pytest.fixture()
def svc(tmp_path):
    f = FakeCasdoor()
    f.seed("19893173727", "admin"); f.seed("adm2", "admin"); f.seed("sup1", "supervisor", ["report"]); f.seed("u1", "user", ["hub"])
    return f, AccountService(f, audit_path=str(tmp_path / "a.log"), revoke_path=str(tmp_path / "rv.json"),
                             overrides_path=str(tmp_path / "ov.json"))


def test_levels_and_readonly(svc):
    f, s = svc
    rows = {r["name"]: r for r in s.snapshot()}
    assert rows["u1"]["level"] == "user" and rows["sup1"]["level"] == "supervisor"
    s.set_level("19893173727", "adm2", "readonly_admin")
    assert "adm2" in f.roles["mhero-readonly-admin"] and "adm2" not in f.roles["mhero-admin"]
    assert {r["name"]: r for r in s.snapshot()}["adm2"]["level"] == "readonly_admin"
    with pytest.raises(AccountError):
        s.set_level("19893173727", "19893173727", "readonly_admin")      # cannot demote self (last super admin)
    s.set_level("19893173727", "sup1", "user")
    assert "sup1" not in f.roles.get("mhero-supervisor", set())


def test_set_app_role(svc, tmp_path):
    f, s = svc
    s.set_app_role("19893173727", "sup1", "report", "admin")
    assert json.loads((tmp_path / "ov.json").read_text()) == {"sup1": {"report": "admin"}}
    assert {r["name"]: r for r in s.snapshot()}["sup1"]["app_roles"] == {"report": "admin"}
    assert "sup1" in json.loads((tmp_path / "rv.json").read_text())         # forced re-login
    s.set_app_role("19893173727", "sup1", "report", "")
    assert json.loads((tmp_path / "ov.json").read_text()) == {}
    for bad in (("adm2", "nss", "user"), ("sup1", "nope", "user"), ("sup1", "nss", "root")):
        with pytest.raises(AccountError):
            s.set_app_role("19893173727", *bad)                             # super admin / unknown system / bad role


def test_overrides_fail_safe_and_locked_write(tmp_path):
    from mhero_auth import roles
    p = tmp_path / "ov.json"
    assert roles.override_for("a", "nss", str(p)) is None                    # absent: no overrides
    roles.write_override(str(p), "A", "nss", "admin")
    assert roles.override_for("a", "nss", str(p)) == "admin"
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert not [x for x in tmp_path.iterdir() if x.name.startswith(".overrides-")]
    p.write_text("{broken")
    assert roles.override_for("a", "nss", str(p)) == "user"                  # corrupt: fail safe to 用户
    assert roles.override_for("b", "vip", str(p)) == "user"
    assert roles.effective_role("supervisor", "b", "vip", global_admin=True, path=str(p)) == "admin"   # 全局超管不受影响
    import pytest
    with pytest.raises(ValueError):
        roles.write_override(str(p), "a", "nss", None)                        # refuses to overwrite a corrupt file
    assert p.read_text() == "{broken"
