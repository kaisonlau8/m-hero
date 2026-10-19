"""账号已登录但没有开通本系统 → 浏览器看到友好 403 页（Ant Design 风格，姓名 + 返回黄页 + 退出登录）；
API/JSON 请求仍是 JSON 403（多一个 hub_url）；未登录 401/302、公开路径、服务令牌行为不变。"""
import asyncio, json

import pytest
from test_core import R, login, mk, sess_cookie

SUP_NO_APP = {"roles": [{"name": "mhero-supervisor"}, {"name": "mhero-app-report"}], "displayName": "张<三>"}
HTML = {"accept": "text/html,application/xhtml+xml"}


def _app_env(env, **kw):
    return {**env, "MHERO_AUTH_REQUIRE_APP": "1", **kw}


def _cookie(env, oidc, app="vip"):
    off = mk(env, app)
    return sess_cookie(off, login(off, oidc, SUP_NO_APP))          # session without the vip app role


def test_decision_html_status_403_and_hub_url(env, oidc):
    c = _cookie(env, oidc)
    a = mk(_app_env(env), "vip")
    d = a.authorize(R(path="/x", headers=HTML, cookies=c))
    assert d.kind == "deny" and d.status == 403
    assert 'id="back-hub"' in d.html and "返回黄页" in d.html and "退出登录" in d.html and "/_auth/logout" in d.html
    assert 'href="https://oa-m-hero.41box.com/"' in d.html and "VIP 保养提醒" in d.html
    assert "张&lt;三&gt;" in d.html and "张<三>" not in d.html           # name is escaped
    assert "viewport" in d.html and "#i-lock" in d.html and "<symbol" in d.html   # mobile + Ant Design icon sprite
    assert d.json_body["hub_url"] == "https://oa-m-hero.41box.com/" and d.json_body["system"] == "vip"
    assert "没有开通本系统" in d.body                                       # plain-text fallback kept


def test_hub_url_configurable(env, oidc):
    c = _cookie(env, oidc)
    a = mk(_app_env(env, MHERO_AUTH_HUB_URL="https://hub.example.test/"), "vip")
    d = a.authorize(R(path="/x", headers=HTML, cookies=c))
    assert 'href="https://hub.example.test/"' in d.html and d.json_body["hub_url"] == "https://hub.example.test/"


def test_callback_denial_has_name_and_page(env, oidc):
    a = mk(_app_env(env), "vip")
    cb = login(a, oidc, {"roles": [{"name": "mhero-supervisor"}, {"name": "mhero-app-report"}], "displayName": "李四"})
    assert cb.status == 403 and "李四" in cb.html and "返回黄页" in cb.html
    nr = login(a, oidc, {"roles": [], "displayName": "王五"})            # no role at all
    assert nr.status == 403 and "王五" in nr.html and nr.json_body["error"] == "no access to this system"   # 用户 without the app role


def test_flask_adapter_html_vs_json(env, oidc, monkeypatch):
    flask = pytest.importorskip("flask")
    from mhero_auth.flask_adapter import init_app
    c = _cookie(env, oidc)
    for k, v in _app_env(env).items():
        monkeypatch.setenv(k, v)
    app = flask.Flask("t"); app.secret_key = "x"
    init_app(app, "vip")
    app.add_url_rule("/x", "x", lambda: "ok"); app.add_url_rule("/api/y", "y", lambda: "ok")
    cl = app.test_client()
    cl.set_cookie("mh_vip", c["mh_vip"])
    r = cl.get("/x", headers=HTML)
    assert r.status_code == 403 and r.mimetype == "text/html" and "返回黄页" in r.get_data(as_text=True)
    r = cl.get("/api/y")
    assert r.status_code == 403 and r.is_json and r.get_json()["hub_url"].startswith("https://") and r.get_json()["error"] == "no access to this system"
    r = cl.get("/x", headers={"Accept": "application/json"})
    assert r.status_code == 403 and r.is_json
    r = cl.get("/x", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 403 and r.is_json
    assert flask.Flask and cl.get("/_auth/logout", follow_redirects=False).status_code == 302
    anon = app.test_client()
    assert anon.get("/x", headers=HTML).status_code == 302 and anon.get("/api/y").status_code == 401


def test_asgi_middleware_html_vs_json(env, oidc, monkeypatch):
    from mhero_auth.asgi import AuthMiddleware
    c = _cookie(env, oidc)
    for k, v in _app_env(env).items():
        monkeypatch.setenv(k, v)

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = AuthMiddleware(inner, "vip")

    def call(path, accept):
        out = []
        async def send(m): out.append(m)
        async def recv(): return {"type": "http.request"}
        scope = {"type": "http", "method": "GET", "path": path, "query_string": b"", "client": ("203.0.113.5", 1),
                 "headers": [(b"accept", accept.encode()), (b"cookie", f"mh_vip={c['mh_vip']}".encode())]}
        asyncio.run(mw(scope, recv, send))
        hd = dict(out[0]["headers"])
        return out[0]["status"], hd.get(b"content-type", b"").decode(), out[1]["body"].decode()

    s, ct, body = call("/x", "text/html")
    assert s == 403 and ct.startswith("text/html") and "返回黄页" in body
    s, ct, body = call("/api/z", "*/*")
    assert s == 403 and ct == "application/json" and json.loads(body)["hub_url"].startswith("https://")
    s, ct, body = call("/x", "application/json")
    assert s == 403 and ct == "application/json"
