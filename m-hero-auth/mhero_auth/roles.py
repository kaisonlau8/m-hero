"""四级角色 + 各系统单独角色（2026-10-19 决定）。

全局身份（Casdoor 角色）：
  超级管理员 admin            -> mhero-admin            所有系统所有权限；唯一能管账号与权限
  只读管理员 readonly_admin   -> mhero-readonly-admin   所有系统可看全部数据；不能提交/申请/审批/触发/改设置/管账号
  督导       supervisor       -> mhero-supervisor       全国数据与全部明细（不脱敏）；可在 supervisor_write_paths 上提交申请
  用户       user             -> 无身份角色              只看汇总（各系统 user_get_paths 白名单）

各系统单独角色（覆盖全局身份）：由黄页「账号管理」（仅超级管理员）写入共享文件 MHERO_AUTH_ROLE_OVERRIDES_FILE，
格式 {"<账号>": {"<系统id>": "<角色>"}}。有效角色 = 全局超级管理员 -> admin；否则 单独角色 or 全局身份。
单独角色不开通系统（是否能进入系统仍看 mhero-app-<id>，全局超级/只读管理员可进入所有系统）。
"""
from __future__ import annotations

import json
import os
import threading

ROLES = ("admin", "readonly_admin", "supervisor", "user")
ROLE_LABEL = {"admin": "超级管理员", "readonly_admin": "只读管理员", "supervisor": "督导", "user": "用户"}
APP_ROLE_LABEL = {"admin": "本系统超级管理员", "readonly_admin": "只读管理员", "supervisor": "督导", "user": "用户"}
# Casdoor role-name suffix for each global level (role name = prefix + suffix, e.g. mhero-readonly-admin)
LEVEL_ROLE_SUFFIX = {"admin": "admin", "readonly_admin": "readonly-admin", "supervisor": "supervisor"}
SUFFIX_LEVEL = {v: k for k, v in LEVEL_ROLE_SUFFIX.items()}
RANK = {"user": 0, "supervisor": 1, "readonly_admin": 2, "admin": 3}

_lock = threading.Lock()
_cache: dict[str, tuple[tuple, dict]] = {}


def overrides_path(env: dict | None = None) -> str:
    e = os.environ if env is None else env
    return (e.get("MHERO_AUTH_ROLE_OVERRIDES_FILE") or "").strip()


def load_overrides(path: str | None = None) -> dict[str, dict[str, str]]:
    """{account: {app: role}}; cached by mtime; unreadable/missing -> {} (= no overrides, global roles apply)."""
    path = overrides_path() if path is None else path
    if not path:
        return {}
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (st.st_mtime_ns, st.st_size, st.st_ino)
    c = _cache.get(path)
    if c and c[0] == key:
        return c[1]
    try:
        raw = json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        raw = {}
    data: dict[str, dict[str, str]] = {}
    if isinstance(raw, dict):
        for user, apps in raw.items():
            if isinstance(apps, dict):
                ok = {str(a): r for a, r in apps.items() if r in ROLES}
                if ok:
                    data[str(user).lower()] = ok
    _cache[path] = (key, data)
    return data


def override_for(user: str, app_id: str, path: str | None = None) -> str | None:
    return load_overrides(path).get((user or "").lower(), {}).get(app_id)


def write_override(path: str, user: str, app_id: str, role: str | None) -> dict:
    """Set (role in ROLES) or clear (role falsy) one override; atomic replace, 0600. Returns the user's overrides after."""
    if not path:
        raise ValueError("MHERO_AUTH_ROLE_OVERRIDES_FILE 未配置")
    if role and role not in ROLES:
        raise ValueError("bad role")
    user = (user or "").lower()
    with _lock:
        try:
            data = json.load(open(path, encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        mine = dict(data.get(user) or {})
        if role:
            mine[app_id] = role
        else:
            mine.pop(app_id, None)
        if mine:
            data[user] = mine
        else:
            data.pop(user, None)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    return mine


def effective_role(global_role: str, user: str, app_id: str, *, global_admin: bool, path: str | None = None) -> str:
    if global_admin:
        return "admin"
    ov = override_for(user, app_id, path)
    if ov:
        return ov
    return global_role if global_role in ROLES else "user"
