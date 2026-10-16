"""移动端导航契约：断点 860px，抽屉 translateX + 遮罩 opacity，桌面规则仍在媒体查询之外。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DS = ROOT / "design-system"
AUTH_DS = ROOT / "m-hero-auth" / "mhero_auth" / "ds"


def test_shared_css_and_auth_copy_match():
    css = (DS / "antd-lite.css").read_text(encoding="utf-8")
    assert css == (AUTH_DS / "antd-lite.css").read_text(encoding="utf-8")
    assert (DS / "cards.js").read_text(encoding="utf-8") == (AUTH_DS / "cards.js").read_text(encoding="utf-8")


def test_mobile_drawer_breakpoint_and_motion():
    css = (DS / "antd-lite.css").read_text(encoding="utf-8")
    assert "@media (max-width: 860px)" in css
    assert "translateX(100%)" in css
    assert "rgba(0, 0, 0, .45)" in css
    assert "cubic-bezier(.23, 1, .32, 1)" in css
    assert ".topbar.open .menu, .topbar.open .ant-menu" in css
    assert ".ant-header.open .menu, .ant-header.open .ant-menu" in css
    assert ".hub-user.open .dd" in css
    assert "打开菜单" in (DS / "cards.js").read_text(encoding="utf-8")
    assert "关闭菜单" in (DS / "cards.js").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in css
    assert ".burger { display: none;" in css.replace("\n", " ") or ".burger {\n  display: none;" in css
    # 桌面水平菜单不放进 860px 查询：.menu { display: flex } 出现在媒体查询之前
    before = css.split("@media (max-width: 860px)", 1)[0]
    assert ".ant-menu, .menu {\n  display: flex;" in before
    menu = before.split("/* ---- 4.3 水平菜单 ---- */", 1)[1].split("/* ---- 4.4", 1)[0]
    assert "translateX" not in menu
    assert "@media" not in menu


def test_burger_api_and_auto_insert_contract():
    """页面级 API 与自动汉堡让位条件：data-burger 识别、幂等、遮罩/抽屉层级与抽屉规格。"""
    css = (DS / "antd-lite.css").read_text(encoding="utf-8")
    js = (DS / "cards.js").read_text(encoding="utf-8")
    # 页面级 API：class="burger" 或 data-burger 属性都能被识别为自带汉堡（桌面隐藏、移动 44px）
    assert "[data-burger]" in css
    assert ".burger, [data-burger]" in css.replace("\n", " ")
    # 自动汉堡仅在顶栏没有任何自带汉堡时插入：id/class 命名的汉堡与 data-no-auto-burger 都要让位
    assert '[id$="-burger"]' in js and "[class$=\"-burger\"]" in js
    assert "data-no-auto-burger" in js
    # 脚本双载幂等：window 标记保证只初始化一次
    assert "__mheroMobileNav" in js
    assert "data-mhero-burger" in js
    # 抽屉规格：宽 min(300px, 82vw)；层级 遮罩 1000 / 抽屉 1001 / 顶栏 >= 100
    assert "min(300px, 82vw)" in css
    assert "--ant-z-nav-mask: 1000" in css
    assert "--ant-z-nav-drawer: 1001" in css
    assert "--ant-z-topbar: 100" in css
    # 打开时锁滚动（ds 驱动与页面自管 body.nav-open 两条路）
    assert "body.nav-open { overflow: hidden; }" in css
    # 顶栏包含块防护：移动端剥离 transform/filter/backdrop-filter，fixed 抽屉不被裁剪
    mobile = css.split("@media (max-width: 860px)", 1)[1]
    assert "backdrop-filter: none !important" in mobile
