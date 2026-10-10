"""Server-side Casdoor admin API client, pinned to ONE organization (mhero).

Credential = a dedicated org-admin Casdoor user (`mhero/svc-accounts`, isAdmin in org mhero only) + a dedicated
application `mhero-account-admin` that has the `password` grant. Casdoor itself refuses anything outside the org
("Unauthorized operation" — verified against Casdoor 4.18), and this client additionally pins `owner` to the org.

The credential file is JSON {"client_id","client_secret","username","password"}; it MUST be mode 600 (we refuse to read it
otherwise) and it is never logged or returned. Used only by server code (hub account page, reportdb identity page).
"""
from __future__ import annotations

import json
import os
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import APP_IDS, APP_ROLE_PREFIX

ROLE_ADMIN, ROLE_SUPERVISOR = "admin", "supervisor"


class CasdoorError(Exception):
    pass


def load_credential(path: str) -> dict:
    st = os.stat(path)
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise CasdoorError(f"credential file {path} must not be readable by group/others (chmod 600)")
    d = json.load(open(path, encoding="utf-8"))
    for k in ("client_id", "client_secret", "username", "password"):
        if not d.get(k):
            raise CasdoorError(f"credential file is missing {k}")
    return d


class CasdoorAdmin:
    def __init__(self, base_url: str, org: str, cred: dict, *, timeout: float = 8.0, clock=time.time):
        if not org:
            raise CasdoorError("org is required")
        self.base, self.org, self._cred, self.timeout, self.clock = base_url.rstrip("/"), org, cred, timeout, clock
        self._tok = ("", 0.0)
        self._lock = threading.RLock()       # role membership is read-modify-write: serialize writers in this process

    @classmethod
    def from_env(cls, env: dict | None = None) -> "CasdoorAdmin | None":
        e = os.environ if env is None else env
        path = e.get("MHERO_ADMIN_CRED_FILE", "")
        base = e.get("MHERO_ADMIN_API_BASE") or e.get("MHERO_AUTH_INTERNAL_ISSUER") or e.get("MHERO_AUTH_ISSUER", "")
        if not path or not base:
            return None
        return cls(base, e.get("MHERO_AUTH_ORG", "mhero"), load_credential(path))

    # -- http
    def _raw(self, method: str, path: str, *, query: dict | None = None, body=None, form: dict | None = None, token: str = "") -> dict:
        url = self.base + path + (("?" + urllib.parse.urlencode(query)) if query else "")
        data, headers = None, {}
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif form is not None:
            data, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
        if token:
            headers["Authorization"] = "Bearer " + token
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                return json.loads(exc.read().decode())
            except Exception:
                raise CasdoorError(f"Casdoor HTTP {exc.code} on {path}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CasdoorError(f"Casdoor unreachable ({type(exc).__name__})")

    def _token(self) -> str:
        with self._lock:
            if self._tok[0] and self._tok[1] > self.clock() + 60:
                return self._tok[0]
            c = self._cred
            r = self._raw("POST", "/api/login/oauth/access_token", form={
                "grant_type": "password", "client_id": c["client_id"], "client_secret": c["client_secret"],
                "username": c["username"], "password": c["password"], "scope": "openid"})
            if not r.get("access_token"):
                raise CasdoorError("admin credential rejected by Casdoor")
            self._tok = (r["access_token"], self.clock() + float(r.get("expires_in") or 3600))
            return self._tok[0]

    def _api(self, method: str, path: str, *, query: dict | None = None, body=None, form: dict | None = None):
        r = self._raw(method, path, query=query, body=body, form=form, token=self._token())
        if r.get("status") != "ok":
            raise CasdoorError(str(r.get("msg") or "Casdoor error")[:200])
        return r.get("data")

    def _uid(self, name: str) -> str:
        if not name or "/" in name:
            raise CasdoorError("bad user name")
        return f"{self.org}/{name}"

    # -- reads
    def list_users(self) -> list[dict]:
        return self._api("GET", "/api/get-users", query={"owner": self.org}) or []

    def get_user(self, name: str) -> dict | None:
        return self._api("GET", "/api/get-user", query={"id": self._uid(name)})

    def list_roles(self) -> dict[str, dict]:
        return {r["name"]: r for r in (self._api("GET", "/api/get-roles", query={"owner": self.org}) or [])}

    # -- writes
    def ensure_roles(self, prefix: str = "mhero-") -> list[str]:
        have, made = self.list_roles(), []
        want = {prefix + ROLE_ADMIN: "管理员", prefix + ROLE_SUPERVISOR: "督导",
                **{f"{prefix}{APP_ROLE_PREFIX}{a}": f"系统权限：{a}" for a in APP_IDS}}
        for name, disp in want.items():
            if name not in have:
                self._api("POST", "/api/add-role", body={"owner": self.org, "name": name, "displayName": disp, "users": [],
                                                        "groups": [], "roles": [], "domains": [], "isEnabled": True})
                made.append(name)
        return made

    def set_membership(self, role: str, user: str, present: bool) -> bool:
        """Idempotent. Returns True when something changed."""
        with self._lock:
            r = self.list_roles().get(role)
            if r is None:
                raise CasdoorError(f"role {role} does not exist (run the bootstrap)")
            uid = self._uid(user)
            users = list(r.get("users") or [])
            if present == (uid in users):
                return False
            r["users"] = [u for u in users if u != uid] + ([uid] if present else [])
            self._api("POST", "/api/update-role", query={"id": f"{self.org}/{role}"}, body=r)
            return True

    def add_user(self, name: str, display: str, password: str, *, need_update_password: bool = True, email: str = "") -> None:
        self._api("POST", "/api/add-user", body={
            "owner": self.org, "name": name, "displayName": display or name, "password": password, "type": "normal-user",
            "email": email, "signupApplication": "mhero-sso", "needUpdatePassword": bool(need_update_password)})

    def set_password(self, name: str, password: str, *, need_update_password: bool = True) -> None:
        """Admin-set password (old password blank is allowed for org admins) + force change at next login."""
        self._api("POST", "/api/set-password", form={"userOwner": self.org, "userName": name, "oldPassword": "", "newPassword": password})
        u = self.get_user(name)
        if u is not None:
            u["needUpdatePassword"] = bool(need_update_password)
            self._api("POST", "/api/update-user", query={"id": self._uid(name), "columns": "need_update_password"}, body=u)

    def set_forbidden(self, name: str, forbidden: bool) -> None:
        u = self.get_user(name)
        if u is None:
            raise CasdoorError("user not found")
        u["isForbidden"] = bool(forbidden)
        self._api("POST", "/api/update-user", query={"id": self._uid(name), "columns": "is_forbidden"}, body=u)

    def set_display(self, name: str, display: str) -> None:
        u = self.get_user(name)
        if u is None:
            raise CasdoorError("user not found")
        u["displayName"] = display
        self._api("POST", "/api/update-user", query={"id": self._uid(name), "columns": "display_name"}, body=u)
