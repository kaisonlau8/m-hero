"""Tiny 'who am I' bar: user name/role + 「账号设置」(Casdoor personal center, change password) + 退出登录.

Framework-neutral: userbar_html(session, cfg, mode) -> str ('' when nothing to show). The Flask adapter injects it before </body>
of HTML responses when init_app(..., userbar=True) or MHERO_AUTH_USERBAR=1. Other apps can also call it from a template.
Hidden when auth is off, anonymous, or the caller is a service token / loopback / break-glass.
"""
from __future__ import annotations

from html import escape

ROLE_LABEL = {"admin": "管理员", "supervisor": "督导"}

_CSS = ("#mhero-userbar{position:fixed;top:10px;right:14px;z-index:2147483000;font:13px/1.4 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;color:#222}"
        "#mhero-userbar .t{display:flex;gap:6px;align-items:center;background:rgba(255,255,255,.97);border:1px solid #d0d7de;border-radius:18px;padding:5px 12px;"
        "box-shadow:0 1px 4px rgba(0,0,0,.12);cursor:pointer;font:inherit;color:#222;max-width:60vw;white-space:nowrap}"
        "#mhero-userbar .t .n{overflow:hidden;text-overflow:ellipsis;max-width:130px}#mhero-userbar .t .c{font-size:10px;color:#789}"
        "#mhero-userbar .r{background:#eef3fb;border-radius:8px;padding:0 6px;font-size:12px;color:#456}"
        "#mhero-userbar .dd{display:none;position:absolute;right:0;top:100%;padding-top:6px;min-width:170px}"
        "#mhero-userbar .dd>div{background:#fff;border:1px solid #d0d7de;border-radius:8px;box-shadow:0 4px 14px rgba(0,0,0,.14);padding:4px 0;overflow:hidden}"
        "#mhero-userbar:hover .dd,#mhero-userbar.open .dd,#mhero-userbar:focus-within .dd{display:block}"
        "#mhero-userbar .dd a{display:block;padding:8px 16px;color:#1f2329;text-decoration:none;white-space:nowrap}"
        "#mhero-userbar .dd a:hover{background:#f0f4ff;color:#0b63ce}#mhero-userbar .dd hr{border:0;border-top:1px solid #eceff3;margin:3px 0}"
        "body>.nav{padding-right:200px!important}@media(max-width:640px){body>.nav{padding-right:130px!important}#mhero-userbar .t .r{display:none}#mhero-userbar{right:8px}}")

_JS = ("(function(){var b=document.getElementById('mhero-userbar');if(!b)return;var t=b.querySelector('.t');"
       "t.addEventListener('click',function(e){e.stopPropagation();var o=b.classList.toggle('open');t.setAttribute('aria-expanded',o?'true':'false');});"
       "document.addEventListener('click',function(e){if(!b.contains(e.target)){b.classList.remove('open');t.setAttribute('aria-expanded','false');}});"
       "document.addEventListener('keydown',function(e){if(e.key==='Escape'){b.classList.remove('open');t.setAttribute('aria-expanded','false');}});})();")


def userbar_html(session, cfg, mode: str, accounts_url: str = "", account_url: str = "") -> str:
    if not session or mode == "off" or getattr(session, "via", "session") != "session":
        return ""
    name = escape(session.display or session.name or "")
    role = escape(ROLE_LABEL.get(session.role, session.role))
    items = f'<a id="mhero-account-link" href="{escape(account_url or cfg.account_url, quote=True)}">账号设置</a>'
    if session.role == "admin" and getattr(session, "ga", False) and accounts_url:
        items += f'<a id="accounts-link" href="{escape(accounts_url, quote=True)}">账号管理（管理员）</a>'
    items += '<hr><a id="mhero-logout-link" href="/_auth/logout">退出登录</a>'
    return (f'<style>{_CSS}</style><div id="mhero-userbar" data-mhero-userbar="1">'
            f'<button type="button" class="t" aria-haspopup="true" aria-expanded="false"><span class="n">{name}</span><span class="r">{role}</span><span class="c">▾</span></button>'
            f'<div class="dd" role="menu"><div>{items}</div></div></div><script>{_JS}</script>')


def inject(body: str, bar: str) -> str:
    if not bar or 'data-mhero-userbar' in body:
        return body
    i = body.lower().rfind("</body>")
    return body + bar if i < 0 else body[:i] + bar + body[i:]
