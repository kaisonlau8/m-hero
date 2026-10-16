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
    assert ".topbar.open .menu, .ant-header.open .ant-menu" in css
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
