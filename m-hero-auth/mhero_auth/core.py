"""Framework-agnostic core: config, signed session cookie, OIDC code flow, JWKS verification,
role model, public-path allowlist, service tokens, break-glass switches.

Only stdlib is required, except `cryptography` for RS256 signature verification
(if it is missing the ID token is verified by calling Casdoor's /api/userinfo instead).
"""
from __future__ import annotations

import base64
import fnmatch
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("mhero_auth")

# Two roles only (decision 2026-10-09). supervisor(督导): sees ALL data unmasked, and may call the
# `supervisor_write_paths` (submit requests). admin: everything, incl. approvals/management/triggers.
ROLE_LEVEL = {"supervisor": 1, "admin": 2}
# Per-system access (2026-10-10): Casdoor roles `mhero-app-<id>`. An account may enter system X iff it has
# mhero-app-X, or is a global admin (mhero-admin). Enforced only when MHERO_AUTH_REQUIRE_APP=1 (default OFF).
APP_IDS = ("report", "nss", "accident", "vip", "district", "cleaner", "hub")
APP_LABEL = {"report": "区域报表", "nss": "NSS 问卷提醒", "accident": "事故车提醒", "vip": "VIP 保养提醒",
             "district": "DMS 爬取控制台", "cleaner": "超时机器人统计", "hub": "控制台黄页"}
APP_ID_OF = {"reportdb": "report"}     # app_name used in init_app -> system id
APP_ROLE_PREFIX = "app-"               # role name = role_prefix + "app-" + id  (mhero-app-report)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
AUTH_PREFIX = "/_auth"


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").replace("\n", ",").split(",") if x.strip()]


# --------------------------------------------------------------------------- config
@dataclass
class AuthConfig:
    app_name: str
    mode: str = "on"                      # on | audit (log only, never blocks) | off
    off_file: str = ""                    # touching this file == MHERO_AUTH=off, no restart needed
    issuer: str = ""                      # e.g. https://sso-m-hero.41box.com
    internal_issuer: str = ""             # optional: backchannel URL for token/JWKS calls (e.g. http://127.0.0.1:8000)
    client_id: str = ""
    client_secret: str = ""
    base_url: str = ""                    # public URL of THIS app, e.g. https://oa-m-hero.41box.com
    session_secret: str = ""
    session_hours: float = 720.0           # 30 days
    revalidate_hours: float = 12.0        # re-check with Casdoor (silent SSO) this often on page loads: role changes/disables take effect
    cookie_name: str = ""                 # default mh_<app>
    hub_url: str = ""                     # 黄页地址（403 友好页「返回黄页」按钮）；空 = 默认黄页
    cookie_domain: str = ""               # empty = host-only (recommended)
    cookie_secure: bool | None = None     # default: base_url startswith https
    org: str = ""                         # required Casdoor organization ("" = any)
    role_prefix: str = "mhero-"           # role names: mhero-admin / mhero-supervisor (or per app: mhero-<app>-admin)
    read_role: str = "supervisor"         # min role for safe methods
    write_role: str = "admin"             # min role for POST/PUT/PATCH/DELETE ...
    supervisor_write_paths: list[str] = field(default_factory=list)   # ... except these globs (supervisor may submit requests)
    public_paths: list[str] = field(default_factory=list)       # fnmatch globs, any method
    public_get_paths: list[str] = field(default_factory=list)   # fnmatch globs, GET/HEAD only
    admin_paths: list[str] = field(default_factory=list)        # globs that need admin
    app_exempt_paths: list[str] = field(default_factory=list)   # globs any logged-in account may open even without mhero-app-<id> (REQUIRE_APP); role rules still apply
    service_tokens: dict[str, tuple[str, str]] = field(default_factory=dict)  # token -> (name, role)
    trust_loopback: bool = False          # allow direct 127.0.0.1 calls that did NOT come through a proxy
    allowed_return_hosts: list[str] = field(default_factory=list)
    account_url: str = ""                 # Casdoor personal center (change password / profile); default <issuer>/account
    require_app: bool = False             # MHERO_AUTH_REQUIRE_APP: enforce mhero-app-<id> (default OFF = old behaviour)
    revoke_file: str = ""                 # MHERO_AUTH_REVOKE_FILE: hub writes {"<user>": epoch}; sessions issued before are void
    clock: Callable[[], float] = time.time
    http_timeout: float = 8.0

    @property
    def app_id(self) -> str:
        return APP_ID_OF.get(self.app_name, self.app_name)

    @classmethod
    def from_env(cls, app_name: str, env: dict | None = None, **overrides) -> "AuthConfig":
        e = os.environ if env is None else env
        default_mode = overrides.pop("default_mode", "on")   # code-level default when no MHERO_AUTH* env is set
        up = "MHERO_AUTH_"
        def g(k, d=""):
            return e.get(f"{up}{app_name.upper().replace('-', '_')}_{k}", e.get(up + k, d))
        tokens: dict[str, tuple[str, str]] = {}
        for item in _csv(g("SERVICE_TOKENS")):         # name:role:token
            parts = item.split(":", 2)
            if len(parts) == 3 and parts[1] in ROLE_LEVEL and len(parts[2]) >= 20:
                tokens[parts[2]] = (parts[0], parts[1])
            else:
                log.error("ignoring malformed service token entry (need name:role:token, token>=20 chars)")
        cfg = cls(
            app_name=app_name,
            mode=e.get(f"MHERO_AUTH_{app_name.upper().replace('-', '_')}") or e.get("MHERO_AUTH") or default_mode,
            off_file=g("OFF_FILE", ""),
            issuer=g("ISSUER").rstrip("/"),
            internal_issuer=g("INTERNAL_ISSUER").rstrip("/"),
            client_id=g("CLIENT_ID"),
            client_secret=g("CLIENT_SECRET"),
            base_url=g("BASE_URL").rstrip("/"),
            session_secret=g("SESSION_SECRET"),
            session_hours=float(g("SESSION_HOURS", "720") or 720),
            revalidate_hours=float(g("REVALIDATE_HOURS", "12") or 12),
            hub_url=g("HUB_URL"),
            cookie_domain=g("COOKIE_DOMAIN"),
            org=g("ORG"),
            role_prefix=g("ROLE_PREFIX", "mhero-"),
            read_role=g("READ_ROLE", "supervisor"),
            write_role=g("WRITE_ROLE", "admin"),
            supervisor_write_paths=_csv(g("SUPERVISOR_WRITE_PATHS")),
            public_paths=_csv(g("PUBLIC_PATHS")),
            public_get_paths=_csv(g("PUBLIC_GET_PATHS")),
            admin_paths=_csv(g("ADMIN_PATHS")),
            app_exempt_paths=_csv(g("APP_EXEMPT_PATHS")),
            service_tokens=tokens,
            trust_loopback=g("TRUST_LOOPBACK", "0") in ("1", "true", "yes"),
            require_app=g("REQUIRE_APP", "0").strip().lower() in ("1", "true", "yes", "on"),
            revoke_file=g("REVOKE_FILE", ""),
            account_url=(g("ACCOUNT_URL") or e.get("SSO_ACCOUNT_URL", "")).strip(),
        )
        for k, v in overrides.items():
            if k in ("public_paths", "public_get_paths", "admin_paths", "supervisor_write_paths"):
                v = list(getattr(cfg, k)) + list(v)       # code defaults extend env
            setattr(cfg, k, v)
        cfg.mode = cfg.mode.lower()
        if cfg.mode not in ("on", "off", "audit"):
            raise ValueError(f"MHERO_AUTH must be on|audit|off, got {cfg.mode!r}")
        if not cfg.account_url:
            cfg.account_url = (cfg.issuer or "https://sso-m-hero.41box.com") + "/account"
        if not cfg.cookie_name:
            cfg.cookie_name = "mh_" + app_name.replace("-", "_")
        if cfg.cookie_secure is None:
            cfg.cookie_secure = cfg.base_url.startswith("https://")
        return cfg

    def validate(self):
        if self.mode == "off":
            return
        missing = [n for n in ("issuer", "client_id", "client_secret", "base_url", "session_secret") if not getattr(self, n)]
        if missing:
            raise RuntimeError(f"mhero_auth[{self.app_name}] mode={self.mode} but missing config: {', '.join(missing)} "
                               f"(set MHERO_AUTH=off to run without login)")
        if len(self.session_secret) < 32:
            raise RuntimeError("MHERO_AUTH_SESSION_SECRET must be >= 32 chars")


# --------------------------------------------------------------------------- data
@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str]          # lower-cased keys
    cookies: dict[str, str]
    query: dict[str, str]
    remote_addr: str = ""

    def h(self, k: str) -> str:
        return self.headers.get(k.lower(), "")


@dataclass
class Session:
    sub: str
    name: str
    display: str
    email: str
    role: str                  # supervisor|admin
    exp: float
    rv: float = 0.0            # revalidate-after (epoch); page loads after this go through Casdoor silently
    via: str = "session"       # session | service-token | loopback | auth-off
    apps: tuple = ()           # systems this account may enter (mhero-app-* roles) — from the ID token at login
    ga: bool = False           # global admin (mhero-admin): may enter every system
    iat: float = 0.0           # session issue time (for force-logout via the revoke file)
    has_apps: bool = True      # False for cookies minted before app roles existed -> re-login when REQUIRE_APP is on


@dataclass
class Decision:
    kind: str                  # allow | redirect | deny
    status: int = 200
    location: str = ""
    body: str = ""
    json_body: dict | None = None
    set_cookies: list[str] = field(default_factory=list)   # raw Set-Cookie header values
    session: Session | None = None
    headers: dict[str, str] = field(default_factory=dict)
    audit_would_block: bool = False
    html: str = ""             # optional HTML body for browser (non-JSON) denials; status/body unchanged


# --------------------------------------------------------------------------- authenticator
class Authenticator:
    def __init__(self, cfg: AuthConfig):
        cfg.validate()
        self.cfg = cfg
        self._jwks: dict[str, Any] = {"at": 0.0, "keys": {}}
        self._disc: dict[str, Any] = {}
        if cfg.mode != "off":
            log.warning("mhero_auth[%s] mode=%s issuer=%s", cfg.app_name, cfg.mode, cfg.issuer)

    # -- switches
    def effective_mode(self) -> str:
        if self.cfg.mode == "off":
            return "off"
        if self.cfg.off_file and os.path.exists(self.cfg.off_file):
            return "off"
        return self.cfg.mode

    # -- cookies
    def _sign(self, payload: dict) -> str:
        body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
        mac = hmac.new(self.cfg.session_secret.encode(), (self.cfg.cookie_name + "." + body).encode(), hashlib.sha256).digest()
        return body + "." + _b64e(mac)

    def _unsign(self, token: str) -> dict | None:
        try:
            body, mac = token.rsplit(".", 1)
            exp = hmac.new(self.cfg.session_secret.encode(), (self.cfg.cookie_name + "." + body).encode(), hashlib.sha256).digest()
            if not hmac.compare_digest(_b64e(exp), mac):
                return None
            return json.loads(_b64d(body))
        except Exception:
            return None

    def _cookie(self, name: str, value: str, max_age: int, path: str = "/") -> str:
        parts = [f"{name}={value}", f"Path={path}", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
        if self.cfg.cookie_secure:
            parts.append("Secure")
        if self.cfg.cookie_domain:
            parts.append(f"Domain={self.cfg.cookie_domain}")
        return "; ".join(parts)

    def _clear(self, name: str) -> str:
        return self._cookie(name, "", 0)

    def session_from(self, req: Request) -> Session | None:
        tok = req.cookies.get(self.cfg.cookie_name)
        d = self._unsign(tok) if tok else None
        if not d or d.get("app") != self.cfg.app_name or d.get("exp", 0) <= self.cfg.clock():
            return None
        s = Session(d["sub"], d["name"], d.get("dn", d["name"]), d.get("em", ""), d["role"], d["exp"], d.get("rv", 0.0),
                    apps=tuple(d.get("ap") or ()), ga=bool(d.get("ga")), iat=float(d.get("iat") or 0), has_apps="ap" in d)
        if self.is_revoked(s):
            return None
        return s

    # -- force logout (revoke file written by the hub account page): session issued before the entry is void
    def _revocations(self) -> dict:
        f = self.cfg.revoke_file
        if not f:
            return {}
        try:
            st = os.stat(f)
        except OSError:
            return {}
        c = getattr(self, "_rev_cache", None)
        key = (st.st_mtime_ns, st.st_size, st.st_ino)
        if c and c[0] == key:
            return c[1]
        try:
            data = json.load(open(f, encoding="utf-8"))
            data = {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except Exception:
            log.error("mhero_auth: unreadable revoke file %s", f)
            data = {}
        self._rev_cache = (key, data)
        return data

    def is_revoked(self, s: Session) -> bool:
        rev = self._revocations()
        if not rev:
            return False
        return s.iat < max(rev.get(s.name, 0.0), rev.get("*", 0.0))

    # -- per-system access
    def has_access(self, s: Session) -> bool:
        if s.via != "session":
            return True            # service tokens / loopback are not accounts
        if self.cfg.app_id == "hub":
            return s.ga or bool(s.apps)     # the 黄页 is the entry point: any account with at least one system may open it (it only lists their own cards)
        return s.ga or self.cfg.app_id in s.apps

    # -- policy helpers
    def _match(self, path: str, pats: list[str]) -> bool:
        return any(fnmatch.fnmatchcase(path, p) for p in pats)

    def is_public(self, req: Request) -> bool:
        if req.path.startswith(AUTH_PREFIX + "/"):
            return True
        if self._match(req.path, self.cfg.public_paths):
            return True
        return req.method in ("GET", "HEAD") and self._match(req.path, self.cfg.public_get_paths)

    def required_role(self, req: Request) -> str:
        if self._match(req.path, self.cfg.admin_paths):
            return "admin"
        if req.method in SAFE_METHODS:
            return self.cfg.read_role
        if self._match(req.path, self.cfg.supervisor_write_paths):
            return "supervisor"
        return self.cfg.write_role

    @staticmethod
    def wants_json(req: Request) -> bool:
        return (req.path.startswith("/api/") or "application/json" in req.h("accept")
                or req.h("x-requested-with").lower() == "xmlhttprequest") and "text/html" not in req.h("accept").split(",")[0]

    def _service_token(self, req: Request) -> Session | None:
        if not self.cfg.service_tokens:
            return None
        auth = req.h("authorization")
        tok = auth[7:].strip() if auth.lower().startswith("bearer ") else req.h("x-mhero-token")
        if not tok:
            return None
        found = None
        for known, ident in self.cfg.service_tokens.items():   # constant-time over all entries
            if hmac.compare_digest(known.encode(), tok.encode()):
                found = ident
        if not found:
            return None
        return Session("svc:" + found[0], found[0], found[0], "", found[1], self.cfg.clock() + 60, via="service-token")

    def _loopback_ok(self, req: Request) -> bool:
        if not self.cfg.trust_loopback or req.remote_addr not in ("127.0.0.1", "::1"):
            return False
        # cloudflared also connects from loopback: anything that went through a proxy carries these.
        proxied = any(req.h(k) for k in ("cf-connecting-ip", "cf-ray", "x-forwarded-for", "x-forwarded-host",
                                          "x-real-ip", "forwarded", "cf-visitor", "cf-ipcountry"))
        return not proxied

    # -- main entry
    def authorize(self, req: Request) -> Decision:
        mode = self.effective_mode()
        if mode == "off":
            return Decision("allow", session=Session("anon", "anonymous", "anonymous", "", "admin", 0, via="auth-off"))
        if req.path.startswith(AUTH_PREFIX + "/"):
            return self.handle_auth_route(req)
        d = self._decide(req)
        if mode == "audit" and d.kind != "allow":
            log.warning("mhero_auth[%s] AUDIT would %s %s %s", self.cfg.app_name, d.kind, req.method, req.path)
            return Decision("allow", audit_would_block=True)
        return d

    def _decide(self, req: Request) -> Decision:
        if self.is_public(req):
            return Decision("allow")
        s = self._service_token(req)
        if s:
            return self._check_role(req, s)
        if self._loopback_ok(req):
            return Decision("allow", session=Session("loopback", "loopback", "loopback", "", "supervisor", 0, via="loopback"))
        s = self.session_from(req)
        if s and self.cfg.require_app and not s.has_apps:
            s = None        # old cookie without app info: send through login once (silent SSO) so it is re-minted
        if not s:
            if self.wants_json(req):
                return Decision("deny", 401, json_body={"error": "unauthorized", "login": self.cfg.base_url + AUTH_PREFIX + "/login"})
            nxt = req.path + (("?" + urllib.parse.urlencode(req.query)) if req.query else "")
            return Decision("redirect", 302, location=f"{AUTH_PREFIX}/login?next={urllib.parse.quote(nxt, safe='')}")
        if s.rv and s.rv <= self.cfg.clock() and req.method == "GET" and not self.wants_json(req) \
                and "text/html" in req.h("accept"):
            # time to re-check with Casdoor (silent when the SSO session is alive): picks up role changes / disabled users
            nxt = req.path + (("?" + urllib.parse.urlencode(req.query)) if req.query else "")
            return Decision("redirect", 302, location=f"{AUTH_PREFIX}/login?next={urllib.parse.quote(nxt, safe='')}")
        if req.method not in SAFE_METHODS and not self._same_origin(req):
            return Decision("deny", 403, json_body={"error": "cross-site request blocked"}, body="cross-site request blocked")
        if self.cfg.require_app and not self.has_access(s) and not self._match(req.path, self.cfg.app_exempt_paths):
            return self._no_app(s)
        return self._check_role(req, s)

    def _no_app(self, s: Session | None = None, name: str = "") -> Decision:
        from .forbidden import DEFAULT_HUB_URL, render_no_access
        label = APP_LABEL.get(self.cfg.app_id, self.cfg.app_id)
        hub = self.cfg.hub_url or DEFAULT_HUB_URL
        try:
            page = render_no_access((s.display or s.name) if s else name, label, hub, AUTH_PREFIX + "/logout")
        except Exception:       # never let the friendly page break the 403 itself
            log.exception("render_no_access failed")
            page = ""
        return Decision("deny", 403, session=s, body="403 你的账号没有开通本系统（%s）的访问权限，请联系管理员。" % label, html=page,
                        json_body={"error": "no access to this system", "system": self.cfg.app_id, "hub_url": hub})

    def _check_role(self, req: Request, s: Session) -> Decision:
        need = self.required_role(req)
        if ROLE_LEVEL[s.role] < ROLE_LEVEL[need]:
            return Decision("deny", 403, json_body={"error": "forbidden", "need": need, "have": s.role},
                            body=f"403 权限不足：需要 {need}，当前角色 {s.role}", session=s)
        return Decision("allow", session=s)

    def _same_origin(self, req: Request) -> bool:
        sfs = req.h("sec-fetch-site")
        if sfs and sfs not in ("same-origin", "none"):
            return False
        origin = req.h("origin")
        return not origin or origin.rstrip("/") == self.cfg.base_url

    # -- OIDC plumbing
    def _issuer_back(self) -> str:
        return self.cfg.internal_issuer or self.cfg.issuer

    def _http(self, url: str, data: dict | None = None, headers: dict | None = None) -> dict:
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        r = urllib.request.Request(url, data=body, headers=headers or {})
        with urllib.request.urlopen(r, timeout=self.cfg.http_timeout) as resp:
            return json.loads(resp.read().decode())

    def jwks(self, force: bool = False) -> dict:
        if force or not self._jwks["keys"] or self.cfg.clock() - self._jwks["at"] > 3600:
            doc = self._http(self._issuer_back() + "/.well-known/jwks")
            self._jwks = {"at": self.cfg.clock(), "keys": {k.get("kid"): k for k in doc.get("keys", [])}}
        return self._jwks["keys"]

    def verify_id_token(self, token: str, nonce: str) -> dict:
        h, p, sig = token.split(".")
        header = json.loads(_b64d(h))
        claims = json.loads(_b64d(p))
        if header.get("alg") != "RS256":
            raise ValueError("unexpected alg")
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        keys = self.jwks()
        jwk = keys.get(header.get("kid")) or self.jwks(force=True).get(header.get("kid"))
        if not jwk:
            raise ValueError("unknown signing key")
        pub = rsa.RSAPublicNumbers(int.from_bytes(_b64d(jwk["e"]), "big"), int.from_bytes(_b64d(jwk["n"]), "big")).public_key()
        pub.verify(_b64d(sig), f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())   # raises on bad sig
        now = self.cfg.clock()
        if claims.get("iss") != self.cfg.issuer:
            raise ValueError("bad iss")
        aud = claims.get("aud")
        if self.cfg.client_id not in (aud if isinstance(aud, list) else [aud]):
            raise ValueError("bad aud")
        if claims.get("exp", 0) <= now - 30 or claims.get("nbf", 0) > now + 30:
            raise ValueError("expired / not yet valid")
        if nonce and claims.get("nonce") != nonce:
            raise ValueError("bad nonce")
        return claims

    def role_from_claims(self, claims: dict) -> str | None:
        if self.cfg.org and claims.get("owner") != self.cfg.org:
            return None
        if claims.get("isForbidden") or claims.get("isDeleted"):
            return None
        names = []
        for r in claims.get("roles") or []:
            names.append(r.get("name") if isinstance(r, dict) else str(r))
        best = 0
        pfx, app = self.cfg.role_prefix, self.cfg.app_name
        for n in names:
            for scope in (pfx, f"{pfx}{app}-"):          # global (mhero-admin) or per-app (mhero-hub-supervisor)
                if n.startswith(scope) and n[len(scope):] in ROLE_LEVEL:
                    best = max(best, ROLE_LEVEL[n[len(scope):]])
        return {v: k for k, v in ROLE_LEVEL.items()}.get(best)

    def apps_from_claims(self, claims: dict) -> tuple[tuple, bool]:
        """-> (systems the account may enter, is_global_admin). Names: mhero-app-<id>; a per-system role of THIS app
        (mhero-<app>-admin|supervisor) also counts as access to this app; global admin enters everything."""
        names = []
        for r in claims.get("roles") or []:
            names.append(r.get("name") if isinstance(r, dict) else str(r))
        pfx = self.cfg.role_prefix
        apps = {n[len(pfx) + len(APP_ROLE_PREFIX):] for n in names if n.startswith(pfx + APP_ROLE_PREFIX)}
        apps = {a for a in apps if a in APP_IDS}
        ga = (pfx + "admin") in names
        for lvl in ROLE_LEVEL:
            if f"{pfx}{self.cfg.app_name}-{lvl}" in names:
                apps.add(self.cfg.app_id)
        return tuple(sorted(apps)), ga

    def _safe_next(self, nxt: str) -> str:
        if not nxt or not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or nxt.startswith(AUTH_PREFIX):
            return "/"
        return nxt

    # -- /_auth/* routes
    def handle_auth_route(self, req: Request) -> Decision:
        route = req.path[len(AUTH_PREFIX):]
        if route == "/login":
            return self._login(req)
        if route == "/callback":
            return self._callback(req)
        if route == "/logout":
            return self._logout(req)
        if route == "/me":
            s = self.session_from(req)
            if not s:
                return Decision("deny", 401, json_body={"authenticated": False})
            return Decision("allow", status=200, json_body={"authenticated": True, "name": s.name, "display": s.display,
                                                            "email": s.email, "role": s.role, "exp": s.exp, "apps": list(s.apps), "global_admin": s.ga}, session=s)
        return Decision("deny", 404, body="not found", json_body={"error": "not found"})

    def _login(self, req: Request) -> Decision:
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        nxt = self._safe_next(req.query.get("next", "/"))
        ck = self._sign({"app": self.cfg.app_name, "st": state, "n": nonce, "next": nxt, "exp": self.cfg.clock() + 600})
        q = urllib.parse.urlencode({"client_id": self.cfg.client_id, "response_type": "code", "scope": "openid profile email",
                                    "redirect_uri": self.cfg.base_url + AUTH_PREFIX + "/callback", "state": state, "nonce": nonce})
        return Decision("redirect", 302, location=f"{self.cfg.issuer}/login/oauth/authorize?{q}",
                        set_cookies=[self._cookie(self.cfg.cookie_name + "_st", ck, 600, AUTH_PREFIX)])

    def _fail(self, status: int, msg: str) -> Decision:
        return Decision("deny", status, body=msg, json_body={"error": msg},
                        set_cookies=[])

    def _callback(self, req: Request) -> Decision:
        if not req.query.get("code") and not req.query.get("error") and not req.query.get("state"):
            return Decision("redirect", 302, location="/")      # coming back from the Casdoor logout (post_logout_redirect_uri = this URL)
        st = self._unsign(req.cookies.get(self.cfg.cookie_name + "_st", "") or "")
        if req.query.get("error"):
            return self._fail(403, "login failed: " + req.query.get("error", "")[:80])
        if (not st or st.get("app") != self.cfg.app_name or st["exp"] <= self.cfg.clock()
                or not hmac.compare_digest(st["st"], req.query.get("state", ""))):
            return self._fail(400, "invalid or expired login state, please retry")
        code = req.query.get("code")
        if not code:
            return self._fail(400, "missing code")
        try:
            tok = self._http(self._issuer_back() + "/api/login/oauth/access_token", {
                "grant_type": "authorization_code", "client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret,
                "code": code, "redirect_uri": self.cfg.base_url + AUTH_PREFIX + "/callback"})
            claims = self.verify_id_token(tok["id_token"], st["n"])
        except Exception as exc:                     # network, signature, claims
            log.warning("mhero_auth[%s] login rejected: %s: %s", self.cfg.app_name, type(exc).__name__, exc)
            return self._fail(401, "login verification failed")
        role = self.role_from_claims(claims)
        if not role:
            log.warning("mhero_auth[%s] user %s has no role for this app", self.cfg.app_name, claims.get("name"))
            d = self._no_app(name=claims.get("displayName") or claims.get("name") or "")
            d.body = "403 你的账号没有访问本系统的权限，请联系管理员。"
            d.json_body = {**(d.json_body or {}), "error": "no role for this app"}
            d.set_cookies = [self._clear(self.cfg.cookie_name + "_st")]
            return d
        apps, ga = self.apps_from_claims(claims)
        nxt_path = urllib.parse.urlsplit(self._safe_next(st.get("next", "/"))).path
        if self.cfg.require_app and not (ga or self.cfg.app_id in apps or (self.cfg.app_id == "hub" and apps)
                                         or self._match(nxt_path, self.cfg.app_exempt_paths)):
            log.warning("mhero_auth[%s] %suser %s has no mhero-app-%s role", self.cfg.app_name,
                        "AUDIT would deny: " if self.effective_mode() == "audit" else "", claims.get("name"), self.cfg.app_id)
            if self.effective_mode() != "audit":
                d = self._no_app(name=claims.get("displayName") or claims.get("name") or "")
                d.set_cookies = [self._clear(self.cfg.cookie_name + "_st")]
                return d
        life = min(self.cfg.session_hours * 3600, max(60, claims["exp"] - self.cfg.clock()))
        exp = self.cfg.clock() + life
        ck = self._sign({"app": self.cfg.app_name, "sub": claims.get("sub", ""), "name": claims.get("name", ""),
                         "dn": claims.get("displayName") or claims.get("name", ""), "em": claims.get("email", ""),
                         "role": role, "exp": exp, "rv": self.cfg.clock() + self.cfg.revalidate_hours * 3600,
                         "ap": list(apps), "ga": ga, "iat": self.cfg.clock()})
        return Decision("redirect", 302, location=self._safe_next(st.get("next", "/")),
                        set_cookies=[self._cookie(self.cfg.cookie_name, ck, int(life)),
                                     self._clear(self.cfg.cookie_name + "_st")])

    def _logout(self, req: Request) -> Decision:
        clear = [self._clear(self.cfg.cookie_name)]
        # end Casdoor SSO session as well, then come back to this app (which will ask for login again)
        loc = f"{self.cfg.issuer}/api/logout?" + urllib.parse.urlencode(
            {"post_logout_redirect_uri": self.cfg.base_url + AUTH_PREFIX + "/callback", "client_id": self.cfg.client_id})
        return Decision("redirect", 302, location="/" if req.query.get("sso") == "0" else loc, set_cookies=clear)
