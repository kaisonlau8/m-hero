"""Account-management policy on top of CasdoorAdmin: who may do what, last-admin / self-lockout guards, audit log,
force-logout (revoke file) and the two-step confirmation token used by the hub page.

Model: level = at most one of mhero-admin (超级管理员) / mhero-readonly-admin (只读管理员) / mhero-supervisor (督导);
none = 用户 (user). Systems = mhero-app-<id> roles. An account can enter system X iff it has mhero-app-X or is a global
super / read-only admin. Per-system role overrides (hub-managed JSON file, see roles.py) refine the role inside one system. Initial / reset passwords are ALWAYS typed by the
admin (never generated); every created / reset account must change its password at first login (Casdoor needUpdatePassword).
Nothing here ever logs a password.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time

from .casdoor_admin import ROLE_ADMIN, ROLE_READONLY_ADMIN, ROLE_SUPERVISOR, CasdoorAdmin
from .core import APP_IDS, APP_LABEL, APP_ROLE_PREFIX
from . import roles as _roles

LEVELS = dict(_roles.ROLE_LABEL)        # admin 超级管理员 / readonly_admin 只读管理员 / supervisor 督导 / user 用户
RESERVED = {"admin", "root", "built-in", "svc-accounts", "system", "anonymous"}   # never creatable / editable here
NAME_RE = re.compile(r"^(?:[a-z][a-z0-9._-]{2,31}|1[3-9]\d{9})$")   # lowercase-letter-led name, or an 11-digit mobile number
MIN_PASSWORD = 10


class AccountError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def check_password(name: str, pw: str) -> None:
    if len(pw) < MIN_PASSWORD or not (re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw) and re.search(r"\d", pw)):
        raise AccountError(f"密码至少 {MIN_PASSWORD} 位，且同时包含大写字母、小写字母和数字")
    if name and name.lower() in pw.lower():
        raise AccountError("密码不能包含用户名")


class AccountService:
    def __init__(self, client: CasdoorAdmin, *, audit_path: str = "", revoke_path: str = "", secret: str = "",
                 prefix: str = "mhero-", clock=time.time, overrides_path: str | None = None):
        self.c, self.audit_path, self.revoke_path, self.prefix, self.clock = client, audit_path, revoke_path, prefix, clock
        self.overrides_path = _roles.overrides_path() if overrides_path is None else overrides_path
        self.secret = (secret or os.urandom(32).hex()).encode()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ naming
    @property
    def r_admin(self): return self.prefix + ROLE_ADMIN
    @property
    def r_sup(self): return self.prefix + ROLE_SUPERVISOR
    @property
    def r_ro(self): return self.prefix + ROLE_READONLY_ADMIN
    def r_app(self, a: str): return f"{self.prefix}{APP_ROLE_PREFIX}{a}"

    # ------------------------------------------------------------------ read
    def snapshot(self) -> list[dict]:
        roles = self.c.list_roles()
        members = {n: {u.split("/", 1)[-1] for u in (r.get("users") or [])} for n, r in roles.items()}
        out = []
        try:
            ov = _roles.load_overrides(self.overrides_path)
        except _roles.OverridesUnavailable:
            ov = {}                                   # 文件损坏：页面照常显示；各系统按「用户」处理，写入会被拒绝
        for u in self.c.list_users():
            n = u["name"]
            if n in RESERVED or u.get("isDeleted"):
                continue
            level = ("admin" if n in members.get(self.r_admin, ()) else "readonly_admin" if n in members.get(self.r_ro, ())
                     else "supervisor" if n in members.get(self.r_sup, ()) else "user")
            out.append({"name": n, "display": u.get("displayName") or n, "email": u.get("email") or "",
                        "disabled": bool(u.get("isForbidden")), "level": level, "need_update_password": bool(u.get("needUpdatePassword")),
                        "apps": [a for a in APP_IDS if n in members.get(self.r_app(a), ())], "last_login": u.get("lastSigninTime") or "",
                        "app_roles": dict(ov.get(n.lower(), {}))})
        return sorted(out, key=lambda x: (x["level"] != "admin", x["name"]))

    def active_admins(self, rows: list[dict] | None = None) -> list[str]:
        return [r["name"] for r in (rows if rows is not None else self.snapshot()) if r["level"] == "admin" and not r["disabled"]]

    def _find(self, rows, name):
        for r in rows:
            if r["name"] == name:
                return r
        raise AccountError("账号不存在，或不允许在此处管理", 404)

    # ------------------------------------------------------------------ audit + force logout
    def audit(self, actor: str, action: str, target: str, detail: str = "", ok: bool = True) -> None:
        """One JSON line per action (also denied ones). Never contains passwords."""
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock())), "actor": actor, "action": action,
               "target": target, "detail": detail, "ok": ok}
        if self.audit_path:
            with self._lock:
                with open(self.audit_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                try:
                    os.chmod(self.audit_path, 0o600)
                except OSError:
                    pass

    def recent_audit(self, n: int = 30) -> list[dict]:
        if not self.audit_path or not os.path.exists(self.audit_path):
            return []
        lines = open(self.audit_path, encoding="utf-8").read().splitlines()[-n:]
        out = []
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out

    def force_logout(self, name: str) -> None:
        """Void every app session of `name` issued before now (apps check MHERO_AUTH_REVOKE_FILE). Role caching: without this,
        a role/app change would only apply at the next 12h re-validation; a disabled account within <=12h. name='*' = everyone."""
        if not self.revoke_path:
            return
        with self._lock:
            try:
                data = json.load(open(self.revoke_path, encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            data[name] = self.clock()
            tmp = self.revoke_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.revoke_path)

    # ------------------------------------------------------------------ guarded writes (actor = hub session name)
    def _deny(self, actor, action, target, msg, status=400):
        self.audit(actor, action, target, "DENIED: " + msg, ok=False)
        raise AccountError(msg, status)

    def create(self, actor: str, name: str, display: str, password: str, level: str, apps: list[str]) -> None:
        name = (name or "").strip().lower()
        if not NAME_RE.match(name) or name in RESERVED:
            self._deny(actor, "create", name, "用户名需为 11 位手机号，或 3~32 位小写字母开头（只含小写字母/数字/._-），且不能是保留名")
        if level not in LEVELS:
            self._deny(actor, "create", name, "身份必须是 超级管理员 / 只读管理员 / 督导 / 用户 之一")
        apps = self._apps(apps)
        try:
            check_password(name, password)
        except AccountError as e:
            self._deny(actor, "create", name, str(e))
        rows = self.snapshot()
        if any(r["name"] == name for r in rows) or self.c.get_user(name):
            self._deny(actor, "create", name, "用户名已存在")
        self.c.add_user(name, (display or name).strip(), password, need_update_password=True)
        self._set_level_roles(name, level)
        self._set_app_roles(name, apps)
        self.audit(actor, "create", name, f"level={level} apps={','.join(apps)} (初始密码由管理员设定，首次登录强制改密)")

    def create_bulk(self, actor: str, name: str, display: str, password: str, level: str, apps: list[str]) -> str:
        """Used only by the supervisor bulk import: username = phone number, password chosen by the user (>= 8 chars, shared initial
        password), still forced to change at first login. Idempotent: an existing account is left completely untouched
        (password, level and roles are NOT modified) -> returns 'exists'. Returns 'created'."""
        if not re.fullmatch(r"1[3-9]\d{9}", name or ""):
            raise AccountError("bulk import usernames must be 11-digit mobile numbers")
        if level not in LEVELS or len(password) < 8:
            raise AccountError("bad level / password (>= 8 chars)")
        apps = self._apps(apps)
        if self.c.get_user(name):
            return "exists"
        self.c.add_user(name, (display or name).strip(), password, need_update_password=True)
        self._set_level_roles(name, level)
        self._set_app_roles(name, apps)
        self.audit(actor, "bulk_create", name, f"{display} level={level} apps={','.join(apps)} (bulk import; first login forces password change)")
        return "created"

    def reset_password(self, actor: str, name: str, password: str) -> None:
        self._find(self.snapshot(), name)
        try:
            check_password(name, password)
        except AccountError as e:
            self._deny(actor, "reset_password", name, str(e))
        self.c.set_password(name, password, need_update_password=True)
        self.force_logout(name)
        self.audit(actor, "reset_password", name, "管理员设定新密码，下次登录强制改密；旧会话已作废")

    def set_level(self, actor: str, name: str, level: str) -> None:
        if level not in LEVELS:
            self._deny(actor, "set_level", name, "身份必须是 超级管理员 / 只读管理员 / 督导 / 用户 之一")
        with self._lock:
            rows = self.snapshot()
            t = self._find(rows, name)
            if t["level"] == level:
                return
            if name == actor and level != "admin":
                self._deny(actor, "set_level", name, "不能给自己降权")
            if t["level"] == "admin" and level != "admin" and not [a for a in self.active_admins(rows) if a != name]:
                self._deny(actor, "set_level", name, "不能降级最后一名管理员")
            self._set_level_roles(name, level)
        self.force_logout(name)
        self.audit(actor, "set_level", name, f"{t['level'] or '-'} -> {level}")

    def set_app_role(self, actor: str, name: str, app: str, role: str) -> None:
        """Per-system role override (role '' = follow the global level). Only meaningful for non-super-admins:
        a global super admin is super admin everywhere and cannot be overridden (prevents lock-out)."""
        if app not in APP_IDS:
            self._deny(actor, "set_app_role", name, "未知系统")
        if role and role not in _roles.ROLES:
            self._deny(actor, "set_app_role", name, "角色必须是 超级管理员 / 只读管理员 / 督导 / 用户 之一，或留空跟随统一身份")
        if not self.overrides_path:
            self._deny(actor, "set_app_role", name, "未配置 MHERO_AUTH_ROLE_OVERRIDES_FILE，无法保存系统角色")
        t = self._find(self.snapshot(), name)
        if t["level"] == "admin":
            self._deny(actor, "set_app_role", name, "全局超级管理员在所有系统都是超级管理员，不能单独设置")
        before = t["app_roles"].get(app, "")
        if before == (role or ""):
            return
        try:
            _roles.write_override(self.overrides_path, name, app, role or None)
        except (OSError, ValueError) as exc:
            self._deny(actor, "set_app_role", name, f"保存失败：{exc}")
        self.force_logout(name)
        self.audit(actor, "set_app_role", name, f"{app}: {before or '跟随统一身份'} -> {role or '跟随统一身份'}")

    def set_apps(self, actor: str, name: str, apps: list[str]) -> None:
        apps = self._apps(apps)
        t = self._find(self.snapshot(), name)
        self._set_app_roles(name, apps)
        self.force_logout(name)
        self.audit(actor, "set_apps", name, f"{','.join(t['apps']) or '-'} -> {','.join(apps) or '-'}")

    def set_disabled(self, actor: str, name: str, disabled: bool) -> None:
        act = "disable" if disabled else "enable"
        with self._lock:
            rows = self.snapshot()
            t = self._find(rows, name)
            if disabled:
                if name == actor:
                    self._deny(actor, act, name, "不能停用自己")
                if t["level"] == "admin" and not t["disabled"] and not [a for a in self.active_admins(rows) if a != name]:
                    self._deny(actor, act, name, "不能停用最后一名管理员")
            self.c.set_forbidden(name, disabled)
        self.force_logout(name)
        self.audit(actor, act, name, "")

    def _apps(self, apps) -> list[str]:
        bad = [a for a in apps if a not in APP_IDS]
        if bad:
            raise AccountError("未知系统：" + ",".join(bad))
        return [a for a in APP_IDS if a in set(apps)]

    def _set_level_roles(self, name, level):
        # grant the new level BEFORE revoking others so a super admin is never momentarily without any level
        order = sorted([(self.r_admin, "admin"), (self.r_ro, "readonly_admin"), (self.r_sup, "supervisor")], key=lambda x: x[1] != level)
        for role, lvl in order:
            self.c.set_membership(role, name, level == lvl)

    def _set_app_roles(self, name, apps):
        for a in APP_IDS:
            self.c.set_membership(self.r_app(a), name, a in apps)

    # ------------------------------------------------------------------ two-step confirmation
    def make_token(self, actor: str, action: str, params: dict, ttl: int = 300) -> str:
        exp = int(self.clock()) + ttl
        return f"{exp}.{self._mac(actor, action, params, exp)}"

    def check_token(self, token: str, actor: str, action: str, params: dict) -> bool:
        try:
            exp, mac = token.split(".", 1)
            return int(exp) >= self.clock() and hmac.compare_digest(mac, self._mac(actor, action, params, int(exp)))
        except Exception:
            return False

    def _mac(self, actor, action, params, exp) -> str:
        msg = json.dumps([actor, action, params, exp], sort_keys=True, ensure_ascii=False).encode()
        return hmac.new(self.secret, msg, hashlib.sha256).hexdigest()
