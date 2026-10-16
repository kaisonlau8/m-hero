"""Hub 「账号管理」 page + card filtering, driven through the real Flask app with a fake Casdoor admin client."""
import importlib.util, json, re, sys, time
from pathlib import Path
import pytest
from fakes import FakeCasdoor
from mhero_auth.accounts import AccountService

HUB = Path(__file__).resolve().parents[2] / "m-hero-hub" / "app.py"
SECRET = "s" * 40
PW = "Abcdef12345x"


def load_hub(monkeypatch, tmp_path, require_app=False):
    for k, v in {"MHERO_AUTH": "on", "MHERO_AUTH_ISSUER": "http://127.0.0.1:1", "MHERO_AUTH_CLIENT_ID": "cid", "MHERO_AUTH_CLIENT_SECRET": "x",
                 "MHERO_AUTH_BASE_URL": "http://hub.test", "MHERO_AUTH_SESSION_SECRET": SECRET, "MHERO_AUTH_ORG": "mhero",
                 "MHERO_AUTH_REQUIRE_APP": "1" if require_app else "0", "MHERO_AUTH_REVOKE_FILE": str(tmp_path / "rv.json")}.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("hub_app_under_test", HUB)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m._port_open = lambda *a, **k: True
    fake = FakeCasdoor()
    fake.seed("alice", "admin"); fake.seed("bob", "supervisor", ["report", "hub"])
    svc = AccountService(fake, audit_path=str(tmp_path / "a.log"), revoke_path=str(tmp_path / "rv.json"), secret="k" * 32)
    m.app.config["ACCOUNT_SERVICE"] = svc
    m.app.config["TESTING"] = True
    return m, fake, svc


def cookie(m, name, role, apps=(), ga=False):
    a = m._auth
    return a._sign({"app": "hub", "sub": name, "name": name, "dn": name, "em": "", "role": role, "exp": time.time() + 3600,
                    "rv": time.time() + 3600, "ap": list(apps), "ga": ga, "iat": time.time()})


def client(m, name, role, apps=(), ga=False):
    c = m.app.test_client()
    c.set_cookie("mh_hub", cookie(m, name, role, apps, ga), domain="hub.test")
    return c


H = {"Origin": "http://hub.test"}


def test_accounts_page_admin_only(monkeypatch, tmp_path):
    m, fake, svc = load_hub(monkeypatch, tmp_path)
    assert client(m, "alice", "admin", ga=True).get("/admin/accounts", base_url="http://hub.test").status_code == 200
    r = client(m, "bob", "supervisor").get("/admin/accounts", base_url="http://hub.test")
    assert r.status_code == 403
    r = client(m, "bob", "supervisor").post("/admin/accounts/prepare", base_url="http://hub.test", headers=H, data={"action": "create"})
    assert r.status_code == 403
    assert m.app.test_client().get("/admin/accounts", base_url="http://hub.test").status_code == 302       # anonymous -> login
    assert fake.calls == []


def test_accounts_page_refuses_when_auth_is_off(monkeypatch, tmp_path):
    m, fake, svc = load_hub(monkeypatch, tmp_path)
    flag = tmp_path / "off"; flag.write_text("1"); m._auth.cfg.off_file = str(flag)       # break-glass active
    r = m.app.test_client().get("/admin/accounts", base_url="http://hub.test")
    assert r.status_code == 403                                                           # never an open admin page


def test_create_requires_confirmation_step(monkeypatch, tmp_path):
    m, fake, svc = load_hub(monkeypatch, tmp_path)
    c = client(m, "alice", "admin", ga=True)
    form = {"action": "create", "name": "dave", "display": "戴维", "password": PW, "level": "supervisor", "apps": ["report", "nss"]}
    r = c.post("/admin/accounts/prepare", base_url="http://hub.test", headers=H, data=form)
    assert r.status_code == 200 and b"confirm-go" in r.data and "dave" not in fake.users
    tok = re.search(rb'name="token" value="([^"]+)"', r.data).group(1).decode()
    assert PW.encode() not in r.data.split(b'id="acct-table"')[0].split(b"confirm-box")[0]      # not echoed outside the hidden field
    # forged execute without / with wrong token -> nothing happens
    for t in ("", "123.abc", tok):
        r = c.post("/admin/accounts/execute", base_url="http://hub.test", headers=H, data={**form, "level": "admin", "token": t})
        assert r.status_code == 400 and "dave" not in fake.users
    r = c.post("/admin/accounts/execute", base_url="http://hub.test", headers=H, data={**form, "token": tok})
    assert r.status_code == 302 and "dave" in fake.users and fake.users["dave"]["needUpdatePassword"] is True
    assert {"report", "nss"} == {a for a in ("report", "nss", "vip") if "dave" in fake.roles.get(f"mhero-app-{a}", set())}
    log = open(tmp_path / "a.log").read()
    assert PW not in log and '"actor": "alice"' in log


def test_weak_password_rejected_at_prepare(monkeypatch, tmp_path):
    m, fake, svc = load_hub(monkeypatch, tmp_path)
    r = client(m, "alice", "admin", ga=True).post("/admin/accounts/prepare", base_url="http://hub.test", headers=H,
                                                   data={"action": "create", "name": "dave", "password": "short", "level": "supervisor"})
    assert r.status_code == 400 and "密码至少" in r.get_data(as_text=True)


def test_self_demote_and_last_admin_blocked_via_ui(monkeypatch, tmp_path):
    m, fake, svc = load_hub(monkeypatch, tmp_path)
    c = client(m, "alice", "admin", ga=True)
    for form, word in (({"action": "set_level", "name": "alice", "level": "supervisor"}, "自己"),
                       ({"action": "set_disabled", "name": "alice", "disabled": "1"}, "自己")):
        r = c.post("/admin/accounts/prepare", base_url="http://hub.test", headers=H, data=form)
        tok = re.search(rb'name="token" value="([^"]+)"', r.data).group(1).decode()
        r = c.post("/admin/accounts/execute", base_url="http://hub.test", headers=H, data={**form, "token": tok})
        assert r.status_code == 400 and word in r.get_data(as_text=True)
    assert "alice" in fake.roles["mhero-admin"] and not fake.users["alice"]["isForbidden"]


def test_cross_site_post_blocked(monkeypatch, tmp_path):
    m, fake, svc = load_hub(monkeypatch, tmp_path)
    r = client(m, "alice", "admin", ga=True).post("/admin/accounts/prepare", base_url="http://hub.test",
                                                   headers={"Origin": "https://evil.test"}, data={"action": "set_disabled", "name": "bob", "disabled": "1"})
    assert r.status_code == 403


def test_cards_filtered_only_when_flag_on(monkeypatch, tmp_path):
    m, fake, svc = load_hub(monkeypatch, tmp_path, require_app=False)
    html = client(m, "bob", "supervisor", ["report"]).get("/", base_url="http://hub.test").get_data(as_text=True)
    assert "NSS 问卷提醒" in html                                    # flag off: unchanged behaviour
    m, fake, svc = load_hub(monkeypatch, tmp_path, require_app=True)
    html = client(m, "bob", "supervisor", ["report", "hub"]).get("/", base_url="http://hub.test").get_data(as_text=True)
    assert "区域报表" in html and "NSS 问卷提醒" not in html and "VIP 保养提醒" not in html
    api = client(m, "bob", "supervisor", ["report", "hub"]).get("/api/status", base_url="http://hub.test").get_json()
    assert [s["id"] for s in api["services"]] == ["report"]
    html = client(m, "alice", "admin", [], ga=True).get("/", base_url="http://hub.test").get_data(as_text=True)
    assert "NSS 问卷提醒" in html and "账号管理" in html
    html = client(m, "bob", "supervisor", ["report", "hub"]).get("/", base_url="http://hub.test").get_data(as_text=True)
    assert 'id="accounts-link"' not in html
    r = client(m, "carol", "supervisor", ["report"]).get("/", base_url="http://hub.test")        # report only: the 黄页 opens, shows only 报表
    assert r.status_code == 200 and "区域报表" in r.get_data(as_text=True) and "NSS 问卷提醒" not in r.get_data(as_text=True)
    r = client(m, "dave", "supervisor", []).get("/", base_url="http://hub.test")                 # no system at all
    assert r.status_code == 403


def test_service_unconfigured_page_does_not_crash(monkeypatch, tmp_path):
    m, fake, svc = load_hub(monkeypatch, tmp_path)
    m.app.config["ACCOUNT_SERVICE"] = None
    monkeypatch.delenv("MHERO_ADMIN_CRED_FILE", raising=False)
    r = client(m, "alice", "admin", ga=True).get("/admin/accounts", base_url="http://hub.test")
    assert r.status_code == 200 and "账号服务未配置" in r.get_data(as_text=True)
