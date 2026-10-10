"""Tiny 'who am I' bar: user name/role + 「账号设置」(Casdoor personal center, change password) + 退出登录.

Framework-neutral: userbar_html(session, cfg, mode) -> str ('' when nothing to show). The Flask adapter injects it before </body>
of HTML responses when init_app(..., userbar=True) or MHERO_AUTH_USERBAR=1. Other apps can also call it from a template.
Hidden when auth is off, anonymous, or the caller is a service token / loopback / break-glass.
"""
from __future__ import annotations

from html import escape

ROLE_LABEL = {"admin": "管理员", "supervisor": "督导"}

_CSS = ("#mhero-userbar{position:fixed;top:8px;right:12px;z-index:2147483000;font:13px/1.4 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
        "background:rgba(255,255,255,.96);color:#222;border:1px solid #d0d7de;border-radius:18px;padding:5px 12px;box-shadow:0 1px 4px rgba(0,0,0,.12);"
        "display:flex;gap:10px;align-items:center}#mhero-userbar a{color:#0b63ce;text-decoration:none}#mhero-userbar a:hover{text-decoration:underline}"
        "#mhero-userbar .r{background:#eef3fb;border-radius:8px;padding:0 6px;font-size:12px;color:#456}")


def userbar_html(session, cfg, mode: str) -> str:
    if not session or mode == "off" or getattr(session, "via", "session") != "session":
        return ""
    name = escape(session.display or session.name or "")
    role = escape(ROLE_LABEL.get(session.role, session.role))
    return (f'<style>{_CSS}</style><div id="mhero-userbar" data-mhero-userbar="1"><span class="u">{name}</span><span class="r">{role}</span>'
            f'<a id="mhero-account-link" href="{escape(cfg.account_url, quote=True)}" target="_blank" rel="noopener">账号设置</a>'
            f'<a id="mhero-logout-link" href="/_auth/logout">退出登录</a></div>')


def inject(body: str, bar: str) -> str:
    if not bar or 'data-mhero-userbar' in body:
        return body
    i = body.lower().rfind("</body>")
    return body + bar if i < 0 else body[:i] + bar + body[i:]
