"""解析器·Markdown — 解析 .md 文件（docs/design.md §16.1）。

能力：
- 读取 .md 文本原样返回，保留标题层级、图片语法、表格等完整格式
- title 取文件名（去扩展名）
- 提取三类图片引用到 ParsedDocument.images（不改写原文，是否处理由 image_service 决定）：
  1) 标准 Markdown 语法 ![alt](url "title")
  2) Obsidian wikilink 嵌入 ![[image.png]] / ![[image.png|alias]]
  3) 内联 HTML <img src="...">

关联方案：docs/design.md §16（多格式文件与过滤设计）；图片方案见 image-progress 约定。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.parsers.base import DocumentParser, ImageRef, ParsedDocument
from app.parsers.registry import register

# 标准 Markdown：![alt](url "optional title")，url 允许用 <> 包裹
_MD_IMAGE_RE = re.compile(
    r"!\[([^\]]*)\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
# Obsidian 嵌入：![[file.png]] / ![[file.png|alias]] / ![[file.png#heading|alias]]
_WIKI_IMAGE_RE = re.compile(r"!\[\[([^\]|#^]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
# 内联 HTML：<img ... src="..." ...>（src 支持双引号 / 单引号 / 无引号）
_HTML_IMG_RE = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))[^>]*>",
    re.IGNORECASE,
)


def collect_image_refs(text: str) -> list[ImageRef]:
    """从 Markdown 文本中提取全部图片引用（按出现位置排序，重叠片段只保留靠前者）。"""
    refs: list[ImageRef] = []

    for m in _MD_IMAGE_RE.finditer(text):
        raw_target = m.group(2)
        if raw_target.startswith("<") and raw_target.endswith(">"):
            raw_target = raw_target[1:-1]
        refs.append(
            ImageRef(
                raw=m.group(0), start=m.start(), end=m.end(),
                alt=m.group(1).strip(), target=raw_target.strip(), kind="md",
            )
        )

    for m in _WIKI_IMAGE_RE.finditer(text):
        alias = (m.group(2) or "").strip()
        refs.append(
            ImageRef(
                raw=m.group(0), start=m.start(), end=m.end(),
                # 纯数字的别名是尺寸（如 |300），不当作替代文本
                alt="" if alias.isdigit() else alias,
                target=m.group(1).strip(), kind="wiki",
            )
        )

    for m in _HTML_IMG_RE.finditer(text):
        src = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if not src:
            continue
        refs.append(
            ImageRef(
                raw=m.group(0), start=m.start(), end=m.end(),
                alt="", target=src, kind="html",
            )
        )

    refs.sort(key=lambda r: r.start)
    # 去除重叠（保留先出现者）：避免同一片段被两种语法重复捕获
    result: list[ImageRef] = []
    last_end = -1
    for ref in refs:
        if ref.start < last_end:
            continue
        result.append(ref)
        last_end = ref.end
    return result


def collect_images(text: str) -> list[str]:
    """从 Markdown 文本中收集所有图片目标（URL / 路径），不修改原文。"""
    return [ref.target for ref in collect_image_refs(text)]


class MarkdownParser(DocumentParser):
    supported_exts = (".md",)

    def parse(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        # 提取图片引用，交由 image_service 决定是否处理；本层不改写原文
        return ParsedDocument(
            content=text,
            title=path.stem,
            mtime=os.path.getmtime(path),
            images=collect_image_refs(text),
        )


register(MarkdownParser())
