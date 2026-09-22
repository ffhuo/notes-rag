"""解析器·PDF — 预留，依赖可选（pymupdf，见 docs/design.md §16.1）。

能力（待实现）：
- 用 pymupdf(fitz) 按页提取文本；页码作为 chunk 的 section 来源写入 meta
- 扫描版 PDF 需 OCR（进阶，不在一期）

启用步骤：
1) uv add pymupdf   （或 uv sync --extra docs）
2) 补全下方 parse() 实现
3) 把 'pdf' 加入 config.ingest_exts 或请求 filters.exts

注意：本模块顶部 import fitz；若未安装，app/parsers/__init__.py 会静默跳过注册，
      不会拖垮主流程（get_parser('.pdf') 返回 None，ingest 跳过该文件）。

关联方案：docs/design.md §16（多格式文件与过滤设计）。
"""
from __future__ import annotations

import os
from pathlib import Path

import fitz  # 可选依赖：未安装时模块 import 失败，由 __init__ 捕获并跳过注册

from app.parsers.base import DocumentParser, ParsedDocument
from app.parsers.registry import register


class PdfParser(DocumentParser):
    supported_exts = (".pdf",)

    def parse(self, path: Path) -> ParsedDocument:
        # TODO(预留): 安装 pymupdf 后补全，示例：
        #   doc = fitz.open(path)
        #   pages = [page.get_text() for page in doc]
        #   text = "\n\n".join(pages)
        #   meta = {"pages": doc.page_count, "source_type": "pdf"}
        #   return ParsedDocument(content=text, title=path.stem,
        #                         mtime=os.path.getmtime(path), meta=meta)
        raise NotImplementedError(
            "PDF 解析预留：请先 `uv add pymupdf` 并补全 parse()（见 docs/design.md §16）"
        )


register(PdfParser())
