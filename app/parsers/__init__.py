"""多格式解析层 — 按扩展名把文件解析为纯文本（docs/design.md §16.2）。

已实现（依赖均为主依赖）：markdown / text / docx / pdf / excel(.xlsx/.xlsm)。

对外主要用 app.parsers.registry.get_parser(ext) 取解析器。
"""
from __future__ import annotations

# 依赖必装：直接导入触发自注册
from app.parsers import markdown  # noqa: F401
from app.parsers import text  # noqa: F401
from app.parsers import docx  # noqa: F401
from app.parsers import pdf  # noqa: F401
from app.parsers import excel  # noqa: F401
