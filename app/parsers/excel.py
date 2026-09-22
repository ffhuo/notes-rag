"""解析器·Excel — 预留，依赖可选（openpyxl，见 docs/design.md §16.1）。

能力（待实现）：
- 用 openpyxl 遍历每个 sheet，转成「表名 + 行列文本」的可读字符串
- 注意：openpyxl 仅支持 .xlsx / .xlsm；老 .xls 需 pandas+engine 或 xlrd（已停更），一期不覆盖

启用步骤：
1) uv add openpyxl   （或 uv sync --extra docs）
2) 补全下方 parse() 实现
3) 把 'xlsx' 加入 config.ingest_exts 或请求 filters.exts

注意：本模块顶部 import openpyxl；若未安装，app/parsers/__init__.py 会静默跳过注册，
      不会拖垮主流程（get_parser('.xlsx') 返回 None，ingest 跳过该文件）。

关联方案：docs/design.md §16（多格式文件与过滤设计）。
"""
from __future__ import annotations

import os
from pathlib import Path

import openpyxl  # 可选依赖：未安装时模块 import 失败，由 __init__ 捕获并跳过注册

from app.parsers.base import DocumentParser, ParsedDocument
from app.parsers.registry import register


class ExcelParser(DocumentParser):
    supported_exts = (".xlsx", ".xls")

    def parse(self, path: Path) -> ParsedDocument:
        # TODO(预留): 安装 openpyxl 后补全，示例：
        #   wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        #   parts = []
        #   for ws in wb.worksheets:
        #       parts.append(f"# {ws.title}")
        #       for row in ws.iter_rows(values_only=True):
        #           cells = ["" if c is None else str(c) for c in row]
        #           parts.append(" | ".join(cells))
        #   text = "\n".join(parts)
        #   meta = {"source_type": "excel", "sheets": wb.sheetnames}
        #   return ParsedDocument(content=text, title=path.stem,
        #                         mtime=os.path.getmtime(path), meta=meta)
        raise NotImplementedError(
            "Excel 解析预留：请先 `uv add openpyxl` 并补全 parse()（见 docs/design.md §16）"
        )


register(ExcelParser())
