"""解析器·Word — 解析 .docx（python-docx，主依赖，见 docs/design.md §16.1）。

能力：
- 按**文档顺序**遍历段落与表格；标题样式转成 Markdown `#` 前缀（切分走 markdown 模式，
  标题层级因此成为 chunk 边界与面包屑）；表格转成**标准 GFM pipe table**（表头 + 分隔行），
  前端 marked 与 chunker 的表格保护都据此识别
- 代码段合并成 markdown ``` 围栏块：判据是「段落样式属于预格式样式」或「段落内全部文字 run
  都是等宽字体」；连续的代码段落一次性成块（行间不插空行，缩进与多行结构因此得以保留）
- 提取**内嵌图片**产出统一的 ImageRef，交给 image_service 走与 markdown 完全相同的链路：
  图片字节在内存里转成 Data URL 存进 ImageRef.target（**不落盘**），正文对应位置插入短标记
  `![图片](docx-media:N)` 作为定位锚点 —— attach_images 正是靠 ref.raw 在 chunk 里定位
- 只支持 .docx（OOXML），老式 .doc 不在覆盖范围内

边界：
- 图片处理（尺寸校验 / 缓存 / 多模态理解 / 回插描述）全部在 image_service，本层只做
  「解析 + 产出引用」，不重复实现任何图片处理逻辑
- 链接式图片（`r:link` 外链）与表格单元格内的图片不提取，表格只取文字

关联方案：docs/design.md §16（多格式文件与过滤设计）；图片方案见 image-progress 约定。
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import docx  # 可选依赖：未安装时模块 import 失败，由 __init__ 捕获并跳过注册
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.parsers.base import (
    DocumentParser,
    ImageRef,
    ParsedDocument,
    fence_block,
    is_mono_font,
)
from app.parsers.registry import register

# Word 标题样式 → 层级。英文版样式名 "Heading N"，中文版「标题 N」，两种都认
_HEADING_RE = re.compile(r"^(?:Heading|标题)\s*([1-6])$")

# Word 里表示「预格式 / 代码」的段落样式名（内置英文名 + 中文版 + 常见自建名），统一小写比较
_CODE_STYLES = frozenset({
    "html preformatted", "html 预设格式",     # 内置：HTML 预设格式（Word 里最标准的写代码样式）
    "plain text", "纯文本",                    # 内置：纯文本
    "macro text", "宏文本",                    # 内置：宏文本
    "code", "代码", "source code", "preformatted text", "预格式文本",
})

# 内嵌图在正文中的定位标记：真实 Data URL（base64）太长，不能进正文
_MARKER_TEMPLATE = "![图片](docx-media:{seq})"


def _heading_level(paragraph: Paragraph) -> int:
    """段落是标题则返回层级（1-6），否则返回 0。"""
    try:
        name = paragraph.style.name or ""
    except Exception:  # noqa: BLE001 —— 样式缺失 / 异常一律当正文处理
        return 0
    if name == "Title":
        return 1
    if name == "Subtitle":
        return 2
    match = _HEADING_RE.match(name)
    return int(match.group(1)) if match else 0


def _run_font(run, paragraph: Paragraph) -> str:
    """取 run 的字体名：直接格式（ascii/hAnsi）优先，取不到再退回段落样式字体。"""
    rpr = run._element.rPr
    if rpr is not None:
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is not None:
            for attr in ("w:ascii", "w:hAnsi"):
                name = fonts.get(qn(attr))
                if name:
                    return name
    try:
        return paragraph.style.font.name or ""
    except Exception:  # noqa: BLE001 —— 样式缺失一律当「取不到」
        return ""


def _is_code_paragraph(paragraph: Paragraph) -> bool:
    """段落是否属于代码段：样式名是预格式样式，或段内全部文字 run 都用等宽字体。

    标题先行排除 —— 用户可能把标题设成等宽字体，那仍是标题而不是代码。
    """
    if _heading_level(paragraph):
        return False
    try:
        style_name = (paragraph.style.name or "").strip().lower()
    except Exception:  # noqa: BLE001
        style_name = ""
    if style_name in _CODE_STYLES:
        return True
    runs = [run for run in paragraph.runs if run.text.strip()]
    return bool(runs) and all(is_mono_font(_run_font(run, paragraph)) for run in runs)


def _iter_blocks(document):
    """按文档顺序产出段落与表格（python-docx 无内置 API，只能遍历 body 子元素）。"""
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _image_marker(drawing, document, images: list[ImageRef]) -> str:
    """把 drawing 里的内嵌图片登记为 ImageRef，返回正文用的定位标记（不可用时返回空串）。"""
    blip = drawing.find(".//" + qn("a:blip"))
    if blip is None:
        return ""
    rid = blip.get(qn("r:embed"))       # 只认内嵌图；r:link（外链图片）不处理
    if not rid:
        return ""
    try:
        image_part = document.part.related_parts[rid]
        blob = image_part.blob
        mime = image_part.content_type or "image/png"
    except Exception:  # noqa: BLE001 —— 关系缺失 / 非图片部件，跳过该图
        return ""
    if not blob:
        return ""
    raw = _MARKER_TEMPLATE.format(seq=len(images) + 1)
    images.append(
        ImageRef(
            raw=raw, start=-1, end=-1, alt="图片",
            target=f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}",
            kind="md",      # 正文里插入的就是标准 Markdown 图片语法
        )
    )
    return raw


def _render_paragraph(paragraph: Paragraph, document, images: list[ImageRef]) -> str:
    """渲染段落：按 run 内子元素的**真实顺序**输出文本与图片标记。

    只认 w:t / w:tab / w:br / w:drawing 四类子元素，其余（书签、批注、域代码）忽略。
    """
    parts: list[str] = []
    for run in paragraph.runs:
        for child in run._element:
            tag = child.tag
            if tag == qn("w:t"):
                parts.append(child.text or "")
            elif tag == qn("w:tab"):
                parts.append("\t")
            elif tag == qn("w:br"):
                parts.append("\n")
            elif tag == qn("w:drawing"):
                marker = _image_marker(child, document, images)
                if marker:
                    parts.append(marker)
    return "".join(parts)


def _render_table(table: Table) -> str:
    """表格渲染为**标准 GFM pipe table**：首行表头 + 分隔行 + 数据行。

    必须每行首尾带 `|` 且表头后紧跟分隔行，否则两个下游都不认这张表：
    前端 marked 不渲染成 <table>（退化成一行带竖线的普通文本），chunker 的
    表格保护正则 `_MD_TABLE_RE` 也匹配不到（大表格会被拦腰切断、丢表头）。
    单元格内的 `|` 转义成 `\\|`（否则多出一列）、换行压成空格（否则表格断行）。
    """
    def _cell(text: str) -> str:
        return text.strip().replace("\n", " ").replace("|", "\\|")

    rows = [
        [_cell(cell.text) for cell in row.cells]
        for row in table.rows
        if row.cells
    ]
    if not rows:
        return ""
    separator = "| " + " | ".join(["---"] * len(rows[0])) + " |"
    lines = ["| " + " | ".join(cells) + " |" for cells in rows]
    return "\n".join([lines[0], separator, *lines[1:]])


class DocxParser(DocumentParser):
    supported_exts = (".docx",)

    def parse(self, path: Path) -> ParsedDocument:
        document = docx.Document(str(path))
        images: list[ImageRef] = []
        blocks: list[str] = []
        code_lines: list[str] = []      # 累积中的连续代码段落（其间空段落也先攒着）

        def flush_code() -> None:
            """收尾一个代码段：够长就产出围栏块，否则退回普通段落。"""
            if not code_lines:
                return
            lines = list(code_lines)
            code_lines.clear()
            while lines and not lines[-1].strip():
                lines.pop()             # 尾部空行不是代码，交给块间空行去分隔
            meaningful = [line for line in lines if line.strip()]
            # 阈值：至少两段，或单段内含软换行 —— Word 里「一段多行」的代码正是后者。
            # 单段单行的等宽文字更像正文里提到的一小段内容，不升级成代码块。
            if len(meaningful) < 2 and not any("\n" in line for line in meaningful):
                blocks.extend(meaningful)
                return
            blocks.append(fence_block("\n".join(lines)))

        for block in _iter_blocks(document):
            if isinstance(block, Table):
                flush_code()
                text = _render_table(block)
            else:
                text = _render_paragraph(block, document, images)
                if _is_code_paragraph(block):
                    code_lines.append(text)
                    continue
                if code_lines and not text.strip():
                    code_lines.append("")   # 代码段内的空行：攒着，flush 时按需裁掉
                    continue
                flush_code()
                level = _heading_level(block)
                if level and text.strip():
                    text = f"{'#' * level} {text.strip()}"
            if text.strip():
                blocks.append(text)

        flush_code()
        content = "\n\n".join(blocks)
        # 回填标记位置：attach_images 靠 ref.raw 定位，偏移仅用于溯源展示
        for ref in images:
            ref.start = content.find(ref.raw)
            ref.end = ref.start + len(ref.raw)

        return ParsedDocument(
            content=content,
            title=path.stem,
            mtime=os.path.getmtime(path),
            meta={"source_type": "docx", "images": len(images)},
            images=images,
        )


register(DocxParser())
