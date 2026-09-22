"""解析器·Markdown — 一期实现，解析 .md 文件（docs/design.md §16.1）。

能力：
- 读取 .md 文本原样返回（标题层级保留，交给 chunker.split_markdown 处理面包屑）
- title 取文件名（去扩展名）

关联方案：docs/design.md §16（多格式文件与过滤设计）。
"""
from __future__ import annotations

import os
from pathlib import Path

from app.parsers.base import DocumentParser, ParsedDocument
from app.parsers.registry import register


class MarkdownParser(DocumentParser):
    supported_exts = (".md",)

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        return ParsedDocument(
            content=text,
            title=path.stem,
            mtime=os.path.getmtime(path),
        )


register(MarkdownParser())
