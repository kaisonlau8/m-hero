"""Tiny 'who am I' bar: user name/role + 「账号设置」(Casdoor personal center, change password) + 退出登录.

Framework-neutral: userbar_html(session, cfg, mode) -> str ('' when nothing to show). The Flask adapter injects it before </body>
of HTML responses when init_app(..., userbar=True) or MHERO_AUTH_USERBAR=1. Other apps can also call it from a template.
Hidden when auth is off, anonymous, or the caller is a service token / loopback / break-glass.

视觉：桌面是 Ant Design v5 Dropdown（token 值内联为字面量，不依赖宿主页样式/外部文件）。
<=860px 只留汉堡按钮，账号设置 / 账号管理 / 退出登录放进右侧抽屉，遮罩与抽屉都有进入和退出过渡。
图标为内联精简 sprite（仅本条用到的 symbol，id 加 i-ub- 前缀避免与宿主页全量 sprite 撞 id）。
"""
from __future__ import annotations

from html import escape

from .ds import sprite_only

ROLE_LABEL = {"admin": "管理员", "supervisor": "督导"}

_UB_ICONS = ("i-user", "i-caret-down", "i-setting", "i-team", "i-logout")

# Ant Design v5 token 值（字面量）：主色 #1677ff/深 #0958d9、文本 rgba(0,0,0,.88)/.45、
# 边框 #d9d9d9、分割线 rgba(5,5,5,.06)、圆角 8(下拉)/6(按钮)/4(tag)、antd 卡片与下拉阴影。
# 断点 860px，与 antd-lite.css 顶栏汉堡一致。抽屉 / 遮罩 300ms，缓动同 Ant Design Drawer。
_CSS = """
#mhero-userbar{position:fixed;top:8px;right:14px;z-index:2147483000;font:14px/1.5714 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei','Helvetica Neue',Helvetica,Arial,sans-serif;color:rgba(0,0,0,.88)}
#mhero-userbar .ai{width:1em;height:1em;fill:currentColor;vertical-align:-.125em;display:inline-block;flex:none}
#mhero-userbar .hb{display:none}
#mhero-userbar .mask{display:none}
#mhero-userbar .who{display:none}
#mhero-userbar .t{display:inline-flex;gap:8px;align-items:center;background:#fff;border:1px solid #d9d9d9;border-radius:8px;padding:4px 12px;min-height:36px;box-shadow:0 1px 2px 0 rgba(0,0,0,.03),0 1px 6px -1px rgba(0,0,0,.02),0 2px 4px 0 rgba(0,0,0,.02);cursor:pointer;font:inherit;color:rgba(0,0,0,.88);max-width:60vw;white-space:nowrap}
#mhero-userbar .t:hover,#mhero-userbar.open .t{border-color:#1677ff;color:#1677ff}
#mhero-userbar .t .ico{width:22px;height:22px;border-radius:50%;background:#e6f4ff;color:#0958d9;display:inline-flex;align-items:center;justify-content:center;flex:none}
#mhero-userbar .t .ico .ai{font-size:12px}
#mhero-userbar .t .n{overflow:hidden;text-overflow:ellipsis;max-width:130px}
#mhero-userbar .r{background:#fafafa;border:1px solid #d9d9d9;border-radius:4px;padding:0 7px;height:20px;line-height:18px;font-size:12px;color:rgba(0,0,0,.88);display:inline-flex;align-items:center;flex:none;font-weight:400}
#mhero-userbar .r.ra{background:#e6f4ff;border-color:#91caff;color:#0958d9}
#mhero-userbar .t .c{color:rgba(0,0,0,.45);font-size:10px}
#mhero-userbar .dd{display:none;position:absolute;right:0;top:calc(100% + 6px);padding:4px;min-width:190px;background:#fff;border:1px solid rgba(5,5,5,.06);border-radius:8px;box-shadow:0 6px 16px 0 rgba(0,0,0,.08),0 3px 6px -4px rgba(0,0,0,.12),0 9px 28px 8px rgba(0,0,0,.05)}
#mhero-userbar:hover .dd,#mhero-userbar.open .dd,#mhero-userbar:focus-within .dd{display:block}
#mhero-userbar .dd a{display:flex;align-items:center;gap:8px;padding:5px 12px;min-height:32px;border-radius:6px;color:rgba(0,0,0,.88);text-decoration:none;white-space:nowrap;font-size:14px}
#mhero-userbar .dd a .ai{color:rgba(0,0,0,.45);font-size:14px}
#mhero-userbar .dd a:hover{background:rgba(0,0,0,.04);color:rgba(0,0,0,.88);text-decoration:none}
#mhero-userbar .dd hr{border:0;border-top:1px solid rgba(5,5,5,.06);margin:4px 8px}
body>.nav{padding-right:220px!important}
#mhero-userbar .hb-ico{position:relative;display:block;width:18px;height:14px}
#mhero-userbar .hb-ico::before,#mhero-userbar .hb-ico::after{content:"";position:absolute;left:0;width:18px;height:2px;background:currentColor;border-radius:1px;transition:transform .3s cubic-bezier(.23,1,.32,1),top .3s cubic-bezier(.23,1,.32,1),box-shadow .3s}
#mhero-userbar .hb-ico::before{top:0;box-shadow:0 6px 0 currentColor}
#mhero-userbar .hb-ico::after{top:12px}
#mhero-userbar.open .hb-ico::before{top:6px;box-shadow:none;transform:rotate(45deg)}
#mhero-userbar.open .hb-ico::after{top:6px;transform:rotate(-45deg)}
@media (max-width:860px){
  body>.nav{padding-right:64px!important}
  #mhero-userbar{top:6px;right:8px}
  #mhero-userbar .t{display:none}
  #mhero-userbar .hb{position:relative;z-index:2;display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;padding:0;border:1px solid #d9d9d9;border-radius:8px;background:#fff;color:rgba(0,0,0,.88);cursor:pointer}
  #mhero-userbar .hb:hover,#mhero-userbar.open .hb{border-color:#1677ff;color:#1677ff}
  #mhero-userbar .mask{display:block;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .3s ease,visibility 0s linear .3s}
  #mhero-userbar.open .mask{opacity:1;visibility:visible;pointer-events:auto;transition:opacity .3s ease,visibility 0s}
  #mhero-userbar .dd,#mhero-userbar:hover .dd,#mhero-userbar:focus-within .dd{display:flex;flex-direction:column;position:fixed;top:52px;right:0;bottom:0;left:auto;width:min(300px,86vw);min-width:0;margin:0;padding:12px 8px 16px;border-radius:0;border:0;border-left:1px solid rgba(5,5,5,.06);z-index:2;overflow:auto;transform:translateX(100%);visibility:hidden;pointer-events:none;transition:transform .3s cubic-bezier(.23,1,.32,1),visibility 0s linear .3s}
  #mhero-userbar.open .dd{transform:translateX(0);visibility:visible;pointer-events:auto;transition:transform .3s cubic-bezier(.23,1,.32,1),visibility 0s}
  #mhero-userbar .who{display:flex;align-items:center;gap:8px;padding:4px 12px 10px;font-weight:600}
  #mhero-userbar .who .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  #mhero-userbar .dd a{min-height:44px;padding:10px 12px}
  body:has(#mhero-userbar.open){overflow:hidden}
}
@media (prefers-reduced-motion:reduce){
  #mhero-userbar .dd,#mhero-userbar .mask,#mhero-userbar .hb-ico::before,#mhero-userbar .hb-ico::after{transition:none!important}
}
"""

_JS = """
(function(){
  var b=document.getElementById('mhero-userbar'); if(!b) return;
  var t=b.querySelector('.t'), hb=b.querySelector('.hb'), mask=b.querySelector('.mask');
  var mq=window.matchMedia('(max-width:860px)');
  function setOpen(o){
    b.classList.toggle('open', !!o);
    var v=o?'true':'false';
    if(t) t.setAttribute('aria-expanded', v);
    if(hb){ hb.setAttribute('aria-expanded', v); hb.setAttribute('aria-label', o?'关闭菜单':'打开菜单'); }
  }
  function toggle(e){ e.stopPropagation(); setOpen(!b.classList.contains('open')); }
  if(t) t.addEventListener('click', toggle);
  if(hb) hb.addEventListener('click', toggle);
  if(mask) mask.addEventListener('click', function(e){ e.stopPropagation(); setOpen(false); });
  document.addEventListener('click', function(e){ if(!b.contains(e.target)) setOpen(false); });
  document.addEventListener('keydown', function(e){ if(e.key==='Escape') setOpen(false); });
  if(mq.addEventListener) mq.addEventListener('change', function(){ if(!mq.matches) setOpen(false); });
})();
"""

_ICON = lambda name: f'<svg class="ai" aria-hidden="true"><use href="#i-ub-{name}"/></svg>'


def userbar_html(session, cfg, mode: str, accounts_url: str = "", account_url: str = "") -> str:
    if not session or mode == "off" or getattr(session, "via", "session") != "session":
        return ""
    name = escape(session.display or session.name or "")
    role = escape(ROLE_LABEL.get(session.role, session.role))
    is_admin = session.role == "admin"
    items = (f'<a id="mhero-account-link" href="{escape(account_url or cfg.account_url, quote=True)}">'
             f'{_ICON("setting")}账号设置</a>')
    if is_admin and getattr(session, "ga", False) and accounts_url:
        items += (f'<a id="accounts-link" href="{escape(accounts_url, quote=True)}">'
                  f'{_ICON("team")}账号管理（管理员）</a>')
    items += f'<hr><a id="mhero-logout-link" href="/_auth/logout">{_ICON("logout")}退出登录</a>'
    who = (f'<div class="who"><span class="n">{name}</span>'
           f'<span class="r{" ra" if is_admin else ""}">{role}</span></div>')
    mini = sprite_only(_UB_ICONS)
    return (f'{mini}<style>{_CSS}</style><div id="mhero-userbar" data-mhero-userbar="1">'
            f'<button type="button" class="hb" aria-label="打开菜单" aria-expanded="false" aria-controls="mhero-userbar-drawer">'
            f'<span class="hb-ico" aria-hidden="true"></span></button>'
            f'<button type="button" class="t" aria-haspopup="true" aria-expanded="false">'
            f'<span class="ico">{_ICON("user")}</span>'
            f'<span class="n">{name}</span>'
            f'<span class="r{" ra" if is_admin else ""}">{role}</span>'
            f'<svg class="ai c" aria-hidden="true"><use href="#i-ub-caret-down"/></svg></button>'
            f'<div class="mask" aria-hidden="true"></div>'
            f'<div class="dd" id="mhero-userbar-drawer" role="menu">{who}{items}</div></div><script>{_JS}</script>')


def inject(body: str, bar: str) -> str:
    if not bar or 'data-mhero-userbar' in body:
        return body
    i = body.lower().rfind("</body>")
    return body + bar if i < 0 else body[:i] + bar + body[i:]
