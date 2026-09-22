"""解析器·Word — 预留，依赖可选（python-docx，见 docs/design.md §16.1）。

能力（待实现）：
- 用 python-docx 提取段落与表格（表格按行转文本）
- 标题样式可近似为面包屑（仅支持 .docx，老 .doc 不在覆盖范围内）

启用步骤：
1) uv add python-docx   （或 uv sync --extra docs）
2) 补全下方 parse() 实现
3) 把 'docx' 加入 config.ingest_exts 或请求 filters.exts

注意：本模块顶部 import docx；若未安装，app/parsers/__init__.py 会静默跳过注册，
      不会拖垮主流程（get_parser('.docx') 返回 None，ingest 跳过该文件）。

关联方案：docs/design.md §16（多格式文件与过滤设计）。
"""
from __future__ import annotations

import os
from pathlib import Path

import docx  # 可选依赖：未安装时模块 import 失败，由 __init__ 捕获并跳过注册

from app.parsers.base import DocumentParser, ParsedDocument
from app.parsers.registry import register


class DocxParser(DocumentParser):
    supported_exts = (".docx",)

    def parse(self, path: Path) -> ParsedDocument:
        # TODO(预留): 安装 python-docx 后补全，示例：
        #   document = docx.Document(path)
        #   parts = [p.text for p in document.paragraphs if p.text.strip()]
        #   for table in document.tables:
        #       for row in table.rows:
        #           parts.append(" | ".join(c.text for c in row.cells))
        #   text = "\n\n".join(parts)
        #   meta = {"source_type": "docx"}
        #   return ParsedDocument(content=text, title=path.stem,
        #                         mtime=os.path.getmtime(path), meta=meta)
        raise NotImplementedError(
            "Word 解析预留：请先 `uv add python-docx` 并补全 parse()（见 docs/design.md §16）"
        )


register(DocxParser())
