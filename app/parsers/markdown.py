"""解析器·Markdown — 解析 .md 文件（docs/design.md §16.1）。

能力：
- 读取 .md 文本原样返回，保留标题层级、图片语法、表格等完整格式
- title 取文件名（去扩展名）
- 收集图片 URL 到 meta["images"]，为后期多模态检索预留入口

关联方案：docs/design.md §16（多格式文件与过滤设计）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.parsers.base import DocumentParser, ParsedDocument
from app.parsers.registry import register

# Markdown 图片语法：![alt](url "optional title")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def collect_images(text: str) -> list[str]:
    """从 Markdown 文本中收集所有图片 URL，不修改原文。"""
    return [m.group(2).strip() for m in _MD_IMAGE_RE.finditer(text)]


class MarkdownParser(DocumentParser):
    supported_exts = (".md",)

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        # 收集图片 URL，为后期多模态检索预留入口；不改写原文
        images = collect_images(text)
        meta: dict = {}
        if images:
            meta["images"] = json.dumps(images, ensure_ascii=False)
        return ParsedDocument(
            content=text,
            title=path.stem,
            mtime=os.path.getmtime(path),
            meta=meta,
        )


register(MarkdownParser())
