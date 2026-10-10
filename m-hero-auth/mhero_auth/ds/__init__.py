"""设计系统资源读取（antd-lite.css / sprite.svg 的本地副本）。

hub、userbar、reportdb 等子系统统一从这里取样式与图标 sprite：
    from mhero_auth.ds import css, sprite
进程内缓存，文件在 design-system/sync.sh 同步时更新。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


def css() -> str:
    """antd-lite.css 全文（<style>{{ css()|safe }}</style> 内联使用）。"""
    return _read("antd-lite.css")


def sprite() -> str:
    """SVG sprite 全文（<body> 开头内联一次，之后 <use href="#i-xxx"/> 引用）。"""
    return _read("sprite.svg")
