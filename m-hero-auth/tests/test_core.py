import urllib.parse as up
import pytest
from mhero_auth.core import AuthConfig, Authenticator, Request


def mk(env, app="hub", **ov):
    return Authenticator(AuthConfig.from_env(app, env=env, **ov))


def R(method="GET", path="/", headers=None, cookies=None, query=None, remote="203.0.113.5"):
    return Request(method, path, {k.lower(): v for k, v in (headers or {}).items()}, cookies or {}, query or {}, remote)


def login(a, oidc, claims=None, nxt="/"):
    """drive login -> callback, return (cookie_header_value, Decision)"""
    d = a._login(R(path="/_auth/login", query={"next": nxt}))
    q = dict(up.parse_qsl(up.urlparse(d.location).query))
    stc = d.set_cookies[0].split(";")[0].split("=", 1)
    oidc.nonce, oidc.claims = q["nonce"], claims or {}
    cb = a._callback(R(path="/_auth/callback", query={"code": "c", "state": q["state"]}, cookies={stc[0]: stc[1]}))
    return cb


def sess_cookie(a, cb):
    name, val = cb.set_cookies[0].split(";")[0].split("=", 1)
    return {name: val}


def test_unauth_redirects_and_api_401(env):
    a = mk(env)
    d = a.authorize(R(path="/dash", query={"x": "1"}))
    assert d.kind == "redirect" and d.location.startswith("/_auth/login?next=%2Fdash%3Fx%3D1")
    d = a.authorize(R(path="/api/status"))
    assert d.status == 401 and d.json_body["error"] == "unauthorized"


def test_login_full_flow_and_roles(env, oidc):
    a = mk(env)
    cb = login(a, oidc, nxt="/reports")
    assert cb.kind == "redirect" and cb.location == "/reports"
    ck = cb.set_cookies[0]
    assert "HttpOnly" in ck and "Secure" in ck and "SameSite=Lax" in ck and "Domain" not in ck
    c = sess_cookie(a, cb)
    assert a.authorize(R(path="/x", cookies=c)).kind == "allow"
    assert a.authorize(R("POST", "/api/run", cookies=c, headers={"Origin": "https://app.example.test"})).kind == "allow"


def test_supervisor_reads_all_but_cannot_write_admin_can(env, oidc):
    a = mk(env, supervisor_write_paths=["/api/requests/*"])
    c = sess_cookie(a, login(a, oidc, {"roles": [{"name": "mhero-supervisor"}]}))
    assert a.authorize(R(path="/x", cookies=c)).kind == "allow"
    d = a.authorize(R("POST", "/api/run", cookies=c))
    assert d.status == 403 and d.json_body["need"] == "admin" and d.json_body["have"] == "supervisor"
    assert a.authorize(R("POST", "/api/requests/new", cookies=c)).kind == "allow"      # submit-request exemption
    c = sess_cookie(a, login(a, oidc, {"roles": [{"name": "mhero-hub-admin"}]}))
    assert a.authorize(R("POST", "/api/run", cookies=c)).kind == "allow"


def test_old_tier_roles_are_ignored(env, oidc):
    a = mk(env)
    for n in ("mhero-viewer", "mhero-operator"):
        assert login(a, oidc, {"roles": [{"name": n}]}).status == 403


def test_revalidation_and_30_day_session(env, oidc):
    a = mk(env)
    t = [10_000.0]
    a.cfg.clock = lambda: t[0]
    d = a._login(R(path="/_auth/login")); q = dict(up.parse_qsl(up.urlparse(d.location).query))
    oidc.nonce, oidc.claims = q["nonce"], {"exp": t[0] + 40 * 86400, "nbf": 0, "roles": [{"name": "mhero-admin"}]}
    cb = a._callback(R(path="/_auth/callback", query={"code": "c", "state": q["state"]}, cookies={"mh_hub_st": d.set_cookies[0].split(";")[0].split("=", 1)[1]}))
    assert f"Max-Age={30 * 86400}" in cb.set_cookies[0]
    c = sess_cookie(a, cb)
    html = {"Accept": "text/html,application/xhtml+xml"}
    assert a.authorize(R(path="/p", cookies=c, headers=html)).kind == "allow"
    t[0] += 13 * 3600                       # past the revalidation window, session still valid
    assert a.authorize(R(path="/p", cookies=c, headers=html)).kind == "redirect"          # silent trip via Casdoor
    assert a.authorize(R(path="/api/status", cookies=c)).kind == "allow"                  # XHR not interrupted
    t[0] += 31 * 86400
    assert a.authorize(R(path="/api/status", cookies=c)).status == 401                    # hard expiry


def test_per_app_role_does_not_leak_to_other_app(env, oidc):
    a = mk(env, "hub")
    cb = login(a, oidc, {"roles": [{"name": "mhero-nss-admin"}]})
    assert cb.status == 403 and "没有访问" in cb.body


def test_admin_paths(env, oidc):
    a = mk(env, admin_paths=["/admin/*"])
    c = sess_cookie(a, login(a, oidc, {"roles": [{"name": "mhero-supervisor"}]}))
    assert a.authorize(R(path="/admin/users", cookies=c)).status == 403


def test_wrong_org_forbidden_user_rejected(env, oidc):
    a = mk(env)
    assert login(a, oidc, {"owner": "other"}).status == 403
    assert login(a, oidc, {"isForbidden": True}).status == 403


def test_bad_signature_rejected(env, oidc):
    a = mk(env)
    oidc.sign_with = oidc.other
    try:
        assert login(a, oidc).status == 401
    finally:
        oidc.sign_with = oidc.key


@pytest.mark.parametrize("over", [{"iss": "http://evil"}, {"aud": ["zzz"]}, {"exp": 1}, {"nonce": "wrong"}])
def test_bad_claims_rejected(env, oidc, over):
    a = mk(env)
    assert login(a, oidc, over).status == 401


def test_state_mismatch_and_missing_cookie(env, oidc):
    a = mk(env)
    d = a._login(R(path="/_auth/login"))
    assert a._callback(R(path="/_auth/callback", query={"code": "c", "state": "bad"},
                         cookies={"mh_hub_st": d.set_cookies[0].split(";")[0].split("=", 1)[1]})).status == 400
    assert a._callback(R(path="/_auth/callback", query={"code": "c", "state": "x"})).status == 400


def test_cookie_tamper_expiry_and_cross_app(env, oidc):
    a = mk(env)
    c = sess_cookie(a, login(a, oidc))
    name, v = next(iter(c.items()))
    assert a.authorize(R(path="/", cookies={name: v[:-2] + "AA"})).kind == "redirect"
    b = mk(env, "nss")        # cookie minted for hub, replayed against nss with SAME secret + forged name
    assert b.authorize(R(path="/", cookies={"mh_nss": v})).kind == "redirect"
    t = [1000.0]
    a2 = mk(env); a2.cfg.clock = lambda: t[0]
    # re-mint with fake clock
    d = a2._login(R(path="/_auth/login")); q = dict(up.parse_qsl(up.urlparse(d.location).query))
    oidc.nonce, oidc.claims = q["nonce"], {"exp": 1000 + 90 * 86400, "nbf": 900}
    cb = a2._callback(R(path="/_auth/callback", query={"code": "c", "state": q["state"]}, cookies={"mh_hub_st": d.set_cookies[0].split(";")[0].split("=", 1)[1]}))
    c2 = sess_cookie(a2, cb)
    assert a2.authorize(R(path="/", cookies=c2)).kind == "allow"
    t[0] += 30 * 86400 + 1
    assert a2.authorize(R(path="/", cookies=c2)).kind == "redirect"


def test_public_paths(env):
    a = mk(env, public_paths=["/feishu/card"], public_get_paths=["/healthz", "/static/*"])
    assert a.authorize(R("POST", "/feishu/card")).kind == "allow"
    assert a.authorize(R("GET", "/healthz")).kind == "allow"
    assert a.authorize(R("POST", "/healthz")).kind != "allow"
    assert a.authorize(R("GET", "/static/a.css")).kind == "allow"
    assert a.authorize(R("GET", "/static/../secret")).kind in ("allow", "redirect")  # normalised by server; globs are literal


def test_env_public_paths_extend_code_defaults(env):
    env["MHERO_AUTH_PUBLIC_PATHS"] = "/a,/b/*"
    a = mk(env, public_paths=["/c"])
    assert a.cfg.public_paths == ["/a", "/b/*", "/c"]


def test_service_token(env):
    tok = "t" * 32
    env["MHERO_AUTH_SERVICE_TOKENS"] = f"watchdog:supervisor:{tok},ops:admin:{'o' * 24}"
    a = mk(env)
    assert a.authorize(R(path="/api/status", headers={"Authorization": f"Bearer {tok}"})).kind == "allow"
    assert a.authorize(R("POST", "/api/run", headers={"Authorization": f"Bearer {tok}"})).status == 403   # supervisor token
    assert a.authorize(R("POST", "/api/run", headers={"X-MHero-Token": "o" * 24})).kind == "allow"
    assert a.authorize(R(path="/api/status", headers={"Authorization": "Bearer nope"})).status == 401


def test_short_service_token_ignored(env):
    env["MHERO_AUTH_SERVICE_TOKENS"] = "w:supervisor:short"
    assert mk(env).cfg.service_tokens == {}


def test_loopback_bypass_only_when_not_proxied(env):
    a = mk(env)
    assert a.authorize(R(path="/x", remote="127.0.0.1")).kind == "redirect"            # off by default
    env["MHERO_AUTH_TRUST_LOOPBACK"] = "1"
    a = mk(env)
    assert a.authorize(R(path="/x", remote="127.0.0.1")).kind == "allow"
    assert a.authorize(R(path="/x", remote="127.0.0.1", headers={"Cf-Connecting-Ip": "1.2.3.4"})).kind == "redirect"
    assert a.authorize(R(path="/x", remote="127.0.0.1", headers={"X-Forwarded-For": "1.2.3.4"})).kind == "redirect"
    assert a.authorize(R(path="/x", remote="203.0.113.5")).kind == "redirect"


def test_break_glass_env_and_file(env, tmp_path):
    env["MHERO_AUTH"] = "off"
    assert mk(env).authorize(R(path="/x")).kind == "allow"
    env["MHERO_AUTH"] = "on"
    flag = tmp_path / "auth-off.flag"
    env["MHERO_AUTH_OFF_FILE"] = str(flag)
    a = mk(env)
    assert a.authorize(R(path="/x")).kind == "redirect"
    flag.write_text("")
    assert a.authorize(R(path="/x")).kind == "allow"      # instant, no restart
    flag.unlink()
    assert a.authorize(R(path="/x")).kind == "redirect"


def test_per_app_mode_override_and_audit(env):
    env["MHERO_AUTH_NSS"] = "off"
    assert mk(env, "nss").effective_mode() == "off" and mk(env, "hub").effective_mode() == "on"
    env["MHERO_AUTH_HUB"] = "audit"
    d = mk(env, "hub").authorize(R(path="/x"))
    assert d.kind == "allow" and d.audit_would_block


def test_misconfig_fails_closed(env):
    env.pop("MHERO_AUTH_CLIENT_SECRET")
    with pytest.raises(RuntimeError):
        mk(env)
    env["MHERO_AUTH"] = "off"
    mk(env)  # off never needs config


def test_csrf_same_origin(env, oidc):
    a = mk(env)
    c = sess_cookie(a, login(a, oidc))
    assert a.authorize(R("POST", "/api/run", cookies=c, headers={"Origin": "https://evil.test"})).status == 403
    assert a.authorize(R("POST", "/api/run", cookies=c, headers={"Sec-Fetch-Site": "cross-site"})).status == 403
    assert a.authorize(R("POST", "/api/run", cookies=c)).kind == "allow"


def test_open_redirect_blocked(env):
    a = mk(env)
    for bad in ("//evil.com", "https://evil.com", "/\\evil.com", "/_auth/logout"):
        d = a._login(R(path="/_auth/login", query={"next": bad}))
        st = a._unsign(d.set_cookies[0].split(";")[0].split("=", 1)[1])
        assert st["next"] == "/"


def test_logout_clears(env):
    a = mk(env)
    d = a.authorize(R(path="/_auth/logout", query={"sso": "0"}))
    assert "Max-Age=0" in d.set_cookies[0] and d.location == "/"
    d = a.authorize(R(path="/_auth/logout"))      # default: also end the Casdoor SSO session (else the next visit silently re-logs in)
    assert d.location.startswith(env["MHERO_AUTH_ISSUER"] + "/api/logout") and "%2F_auth%2Fcallback" in d.location
    assert a.authorize(R(path="/_auth/callback")).location == "/"


def test_cookie_domain_option(env):
    env["MHERO_AUTH_COOKIE_DOMAIN"] = ".41box.com"
    assert "Domain=.41box.com" in mk(env)._cookie("a", "b", 10)


def test_default_mode_param_used_only_when_env_unset(env):
    env.pop("MHERO_AUTH")
    assert AuthConfig.from_env("hub", env=env).mode == "on"
    assert AuthConfig.from_env("hub", env=env, default_mode="off").mode == "off"
    env["MHERO_AUTH_HUB"] = "audit"
    assert AuthConfig.from_env("hub", env=env, default_mode="off").mode == "audit"


def test_userbar_and_account_url(env, oidc):
    from mhero_auth.userbar import userbar_html, inject
    a = mk(env)
    assert a.cfg.account_url == a.cfg.issuer + "/account"
    s = a.session_from(R(path="/", cookies=sess_cookie(a, login(a, oidc))))
    html = userbar_html(s, a.cfg, "on")
    assert 'href="%s/account"' % a.cfg.issuer in html and "账号设置" in html and "/_auth/logout" in html
    assert 'class="t"' in html and "accounts-link" not in html            # dropdown trigger; no admin link unless asked
    assert 'aria-label="打开菜单"' in html and 'id="mhero-userbar-drawer"' in html
    assert "max-width:860px" in html and "translateX(100%)" in html and "关闭菜单" in html
    h2 = userbar_html(s, a.cfg, "on", "/admin/accounts", "/account")
    assert 'href="/account"' in h2 and (("accounts-link" in h2) == (s.role == "admin" and s.ga))
    assert userbar_html(s, a.cfg, "off") == "" and userbar_html(None, a.cfg, "on") == ""
    s.via = "service-token"
    assert userbar_html(s, a.cfg, "on") == ""
    assert inject("<body>x</body>", "BAR") == "<body>xBAR</body>" and inject("<p>x", "BAR") == "<p>xBAR"
    from mhero_auth.core import AuthConfig
    assert AuthConfig.from_env("hub", env={"SSO_ACCOUNT_URL": "https://x/acct"}).account_url == "https://x/acct"
    assert AuthConfig.from_env("hub", env={"MHERO_AUTH_ACCOUNT_URL": "https://y/a", "SSO_ACCOUNT_URL": "https://x"}).account_url == "https://y/a"


def test_browser_probe_does_not_start_login(env):
    """Unauthenticated favicon must 404, not overwrite the OAuth state cookie."""
    a = mk(env)
    d = a._login(R(path="/_auth/login"))
    st_cookie = d.set_cookies[0]
    name, val = st_cookie.split(";")[0].split("=", 1)
    # While a login is in flight, a favicon probe must not redirect to /_auth/login.
    probe = a.authorize(R(path="/favicon.ico", cookies={name: val}))
    assert probe.status == 404 and probe.kind == "deny"
    assert not probe.set_cookies
    # apple-touch too
    assert a.authorize(R(path="/apple-touch-icon.png")).status == 404


def test_state_cookie_cleared_with_auth_path(env, oidc):
    a = mk(env)
    cb = login(a, oidc)
    clears = [c for c in cb.set_cookies if c.startswith(a.cfg.cookie_name + "_st=")]
    assert clears, "expected state-cookie clear"
    assert "Path=/_auth" in clears[0]
    assert "Max-Age=0" in clears[0]


def test_favicon_next_sanitized(env):
    a = mk(env)
    d = a._login(R(path="/_auth/login", query={"next": "/favicon.ico"}))
    q = dict(up.parse_qsl(up.urlparse(d.location).query))
    # next is inside the signed cookie, not the authorize URL; reopen via unsign
    name, val = d.set_cookies[0].split(";")[0].split("=", 1)
    st = a._unsign(val)
    assert st["next"] == "/"


def test_login_state_fail_has_retry_html(env):
    a = mk(env)
    d = a._callback(R(path="/_auth/callback", query={"code": "c", "state": "x"}))
    assert d.status == 400
    assert d.html and "/_auth/login" in d.html
    assert "invalid or expired login state" in d.body
