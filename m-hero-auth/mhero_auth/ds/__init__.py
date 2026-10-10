"""设计系统资源读取（antd-lite.css / sprite.svg 的本地副本）。

hub、userbar、reportdb 等子系统统一从这里取样式与图标 sprite：
    from mhero_auth.ds import css, sprite
进程内缓存，文件在 design-system/sync.sh 同步时更新。
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent

_SYMBOL_RE = re.compile(r"<symbol\b[^>]*id=\"([^\"]+)\"[^>]*>.*?</symbol>", re.S)


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


def css() -> str:
    """antd-lite.css 全文（<style>{{ css()|safe }}</style> 内联使用）。"""
    return _read("antd-lite.css")


def sprite() -> str:
    """SVG sprite 全文（<body> 开头内联一次，之后 <use href="#i-xxx"/> 引用）。"""
    return _read("sprite.svg")


@lru_cache(maxsize=16)
def sprite_only(names: tuple[str, ...], prefix: str = "i-ub-") -> str:
    """只含指定 symbol 的精简 sprite（id 加 prefix 前缀，避免与宿主页全量 sprite 撞 id）。

    userbar 等小组件用：<svg class="ai"><use href="#i-ub-user"/></svg>
    """
    want = set(names)
    parts = []
    for m in _SYMBOL_RE.finditer(_read("sprite.svg")):
        sid = m.group(1)
        if sid in want:
            new_id = prefix + (sid[2:] if sid.startswith("i-") else sid)
            parts.append(m.group(0).replace(f'id="{sid}"', f'id="{new_id}"', 1))
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="0" height="0"'
            ' style="position:absolute" aria-hidden="true">' + "".join(parts) + "</svg>")
