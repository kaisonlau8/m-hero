"""Decision 2026-10-09: the Feishu card link GET {PUBLIC_BASE_URL}/api/report/latest REQUIRES Casdoor login like everything
else on the district console. Only VIP's /feishu/card is public. After login the user must land back on the download."""
import re
import urllib.parse as up
from pathlib import Path

from mhero_auth.core import AuthConfig, Authenticator, Request

PATCHES = Path(__file__).resolve().parents[1] / "patches"


def auth(app="district", **kw):
    env = {"MHERO_AUTH": "on", "MHERO_AUTH_ISSUER": "https://sso.example.test", "MHERO_AUTH_CLIENT_ID": "c",
           "MHERO_AUTH_CLIENT_SECRET": "s", "MHERO_AUTH_BASE_URL": "https://m-hero-district-form.41box.com",
           "MHERO_AUTH_SESSION_SECRET": "k" * 40}
    return Authenticator(AuthConfig.from_env(app, env=env, **kw))


def R(m, p, q=None, accept="text/html"):
    return Request(m, p, {"accept": accept}, {}, q or {}, "203.0.113.9")


def test_district_patch_has_no_public_paths():
    d = (PATCHES / "district-sso.patch").read_text(encoding="utf-8")
    call = re.search(r'\+_mhero_auth_init\(app, "district"([^)]*)\)', d).group(1)
    assert "public" not in call and "/api/report" not in call


def test_only_vip_feishu_card_is_public_across_patches():
    pubs = {}
    for f in PATCHES.glob("*-sso.patch"):
        for m in re.finditer(r'\+_mhero_auth_init\(app, "(\w+)"([^\n]*)', f.read_text(encoding="utf-8")):
            pubs[m.group(1)] = re.findall(r'public(?:_get)?_paths=\[([^\]]*)\]', m.group(2))
    assert {k: v for k, v in pubs.items() if v} == {"vip": ['"/feishu/card"'], "hub": ['"/healthz"']}   # hub /healthz = probe only, no data


def test_unauthenticated_download_redirects_to_login_preserving_url():
    a = auth()
    d = a.authorize(R("GET", "/api/report/latest", accept="text/html,application/xhtml+xml"))
    assert d.kind == "redirect" and d.location == "/_auth/login?next=%2Fapi%2Freport%2Flatest"
    # a link with a query string keeps it too
    d = a.authorize(R("GET", "/api/report/latest", {"d": "1009"}))
    assert up.parse_qs(up.urlparse(d.location).query)["next"] == ["/api/report/latest?d=1009"]
    # login step stores that next and sends the user to Casdoor; callback returns to it (see integration test for the full trip)
    d = a.authorize(R("GET", "/_auth/login", {"next": "/api/report/latest"}))
    st = a._unsign(d.set_cookies[0].split(";")[0].split("=", 1)[1])
    assert st["next"] == "/api/report/latest" and d.location.startswith("https://sso.example.test/login/oauth/authorize")


def test_non_browser_clients_get_401_not_html():
    d = auth().authorize(R("GET", "/api/report/latest", accept="*/*"))
    assert d.status == 401 or d.kind == "redirect"
