"""解析器·注册表 — 按扩展名路由到具体 parser（docs/design.md §16.2）。

能力：
- register(parser): 解析器模块 import 时自注册
- get_parser(ext): 根据扩展名（'.md' / 'md'）返回对应 parser 实例，未注册返回 None

关联方案：docs/design.md §16（多格式文件与过滤设计）。
"""
from __future__ import annotations

from app.parsers.base import DocumentParser, normalize_ext

_PARSERS: dict[str, DocumentParser] = {}


def register(parser: DocumentParser) -> None:
    """注册一个解析器：把其支持的每个扩展名映射到该实例。"""
    for ext in parser.supported_exts:
        _PARSERS[normalize_ext(ext)] = parser


def get_parser(ext: str) -> DocumentParser | None:
    """按扩展名取解析器；未注册（未知格式或依赖缺失）返回 None。"""
    return _PARSERS.get(normalize_ext(ext))
