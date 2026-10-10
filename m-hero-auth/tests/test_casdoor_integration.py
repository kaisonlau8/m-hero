"""Real Casdoor round trip. Runs only when a dev Casdoor is up:
   CASDOOR_DEV_DIR=/workspace/casdoor-dev (contains secrets.json, 600) and http://127.0.0.1:18000 reachable.
Covers Flask + FastAPI adapters end to end (login page redirect -> Casdoor password login -> code -> JWKS-verified
ID token -> role from Casdoor role membership -> cookie -> protected page / 403 for supervisor POST -> logout)."""
import json, os, urllib.parse as up
import pytest, requests

D = os.environ.get("CASDOOR_DEV_DIR", "/workspace/casdoor-dev")
B = "http://127.0.0.1:18000"
try:
    S = json.load(open(f"{D}/secrets.json"))
    requests.get(B + "/.well-known/openid-configuration", timeout=2).raise_for_status()
except Exception:
    pytest.skip("no dev Casdoor", allow_module_level=True)


def casdoor_code(auth_url, user, pw):
    q = dict(up.parse_qsl(up.urlparse(auth_url).query))
    r = requests.post(f"{B}/api/login", params={"clientId": q["client_id"], "responseType": "code", "redirectUri": q["redirect_uri"],
                      "scope": q["scope"], "state": q["state"], "nonce": q["nonce"]},
                      json={"application": "mhero-sso", "organization": "mhero", "username": user, "password": pw, "type": "code"}).json()
    assert r["status"] == "ok", r.get("msg")
    return r["data"], q["state"]


def env(base):
    return {"MHERO_AUTH": "on", "MHERO_AUTH_ISSUER": B, "MHERO_AUTH_CLIENT_ID": S["client_id"], "MHERO_AUTH_CLIENT_SECRET": S["client_secret"],
            "MHERO_AUTH_BASE_URL": base, "MHERO_AUTH_SESSION_SECRET": "z" * 48, "MHERO_AUTH_ORG": "mhero"}


def flask_app(monkeypatch, base):
    from flask import Flask
    from mhero_auth.flask_adapter import init_app
    for k, v in env(base).items():
        monkeypatch.setenv(k, v)
    app = Flask(__name__)

    @app.get("/")
    def i(): return "home"
    @app.post("/api/run")
    def run(): return {"ran": True}
    @app.get("/healthz")
    def hz(): return "ok"
    init_app(app, "hub", public_get_paths=["/healthz"])
    return app


def fastapi_app(monkeypatch, base):
    from fastapi import FastAPI
    from mhero_auth.asgi import AuthMiddleware
    for k, v in env(base).items():
        monkeypatch.setenv(k, v)
    app = FastAPI()

    @app.get("/")
    def i(): return {"home": 1}
    @app.post("/api/run")
    def run(): return {"ran": True}
    app.add_middleware(AuthMiddleware, app_name="reportdb")
    return app


def login_flask(client, base, user, pw):
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"].startswith("/_auth/login")
    r = client.get(r.headers["Location"])
    assert r.status_code == 302 and r.headers["Location"].startswith(B + "/login/oauth/authorize")
    code, state = casdoor_code(r.headers["Location"], user, pw)
    return client.get("/_auth/callback", query_string={"code": code, "state": state})


def test_flask_admin_and_supervisor(monkeypatch):
    base = "http://127.0.0.1:19002"
    app = flask_app(monkeypatch, base)
    c = app.test_client()
    assert c.get("/healthz").status_code == 200
    r = login_flask(c, base, "alice", S["alice_pw"])
    assert r.status_code == 302 and r.headers["Location"] == "/"
    assert c.get("/").data == b"home"
    assert c.post("/api/run", headers={"Origin": base}).json == {"ran": True}
    me = c.get("/_auth/me").json
    assert me["role"] == "admin" and me["name"] == "alice"
    v = app.test_client()
    assert login_flask(v, base, "bob", S["bob_pw"]).status_code == 302
    assert v.get("/").status_code == 200
    r = v.post("/api/run", headers={"Origin": base})
    assert r.status_code == 403 and r.json["have"] == "supervisor"
    assert v.get("/_auth/logout").status_code == 302
    assert v.get("/api/x").status_code == 401


def test_flask_wrong_password_no_session(monkeypatch):
    r = requests.post(f"{B}/api/login", json={"application": "mhero-sso", "organization": "mhero", "username": "alice", "password": "nope", "type": "code"}).json()
    assert r["status"] == "error"


def test_fastapi_admin(monkeypatch):
    from fastapi.testclient import TestClient
    base = "http://127.0.0.1:9013"
    c = TestClient(fastapi_app(monkeypatch, base), follow_redirects=False)
    r = c.get("/")
    assert r.status_code == 302
    r = c.get(r.headers["location"])
    code, state = casdoor_code(r.headers["location"], "alice", S["alice_pw"])
    r = c.get("/_auth/callback", params={"code": code, "state": state})
    assert r.status_code == 302
    assert c.get("/").json() == {"home": 1}
    assert c.post("/api/run", headers={"Origin": base}).json() == {"ran": True}
    assert c.get("/_auth/me").json()["role"] == "admin"
    anon = TestClient(fastapi_app(monkeypatch, base), follow_redirects=False)
    assert anon.post("/api/run").status_code == 401
