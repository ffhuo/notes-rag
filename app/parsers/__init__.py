"""多格式解析层 — 按扩展名把文件解析为纯文本（docs/design.md §16.2）。

已实现：markdown / text / docx / pdf（依赖均为主依赖）。
预留（依赖可选，未安装则跳过注册，不影响主流程）：excel。

对外主要用 app.parsers.registry.get_parser(ext) 取解析器。
"""
from __future__ import annotations

# 必有依赖的解析器：直接导入触发自注册
from app.parsers import markdown  # noqa: F401
from app.parsers import text  # noqa: F401
from app.parsers import docx  # noqa: F401
from app.parsers import pdf  # noqa: F401

# 预留解析器：依赖可选，缺失则静默跳过（不影响 import 与 ingest 主流程）
try:
    from app.parsers import excel  # noqa: F401
except ImportError:
    pass
