"""解析器·PDF — 解析 .pdf（pymupdf，主依赖，见 docs/design.md §16.1）。

能力：
- 按页提取正文；多页 PDF 以 `## 第 N 页` 作为小节标题（切分走 markdown 模式，
  页码因此成为 chunk 边界与面包屑），单页 PDF 不加页码标题
- 按**块版面顺序**输出：文本块出文字，图片块出短标记 `![图片](pdf-image:N)`，真实字节
  以 Data URL 存进 ImageRef.target（**不落盘**）—— 与 Word 内嵌图走同一条 image_service
  链路（尺寸校验 / 缓存 / 多模态理解 / 回插），本层不重复实现任何图片处理逻辑
- **代码段还原成 markdown 围栏块**：连续等宽字体的行合并成一块，并用各行的 x0 偏移除以
  字符宽，把「排版缩进」换算回前导空格（PDF 里缩进是坐标而不是空格，不还原则层级全丢）
- **扫描件友好**（不需要 OCR 引擎）：
  * 扫描页在结构上就是一个整页图片块，因此天然走上面的多模态链路；未配置多模态 LLM 时
    这些页不会产出可检索文字，只在日志里给出告警提示
  * 整页既无文本层、又取不到图片块（CCITT / JBIG2 / 纯矢量绘制页）→ 整页渲染成图兜底
  * 加密 / 损坏的 PDF 主动抛 PdfParseError（加密是其子类），交给作业层记入失败清单，
    失败原因中文化，排查时不必去翻 pymupdf 的英文报错

边界：
- 不做 OCR、不做版面分析（表格按文本行输出，不还原为 Markdown 表格）
- 不提取批注 / 表单域 / 附件；只支持可解码的图片，解码失败时该图保留为空

关联方案：docs/design.md §16（多格式文件与过滤设计）；图片方案见 image-progress 约定。
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import pymupdf  # 主依赖；未安装时由 app/parsers/__init__.py 捕获 ImportError 跳过注册
from loguru import logger

from app.parsers.base import (
    DocumentParser,
    ImageRef,
    ParsedDocument,
    fence_block,
    is_mono_font,
)
from app.parsers.registry import register

# 图片在正文中的定位标记：真实字节（base64）太长，不能进正文。
# attach_images 正是靠 ref.raw 在 chunk 里定位，标记必须与 ref.raw 完全一致。
_MARKER_TEMPLATE = "![图片](pdf-image:{seq})"

# 整页渲染兜底的分辨率：150 DPI ≈ A4 1240×1754，够多模态模型看清正文
_SCAN_RENDER_DPI = 150

# 等宽字符宽 ≈ 字号 × 0.6（Courier 系标准值），仅在取不到实测宽度时回退使用
_MONO_CHAR_RATIO = 0.6

# 代码行成块的最少行数：PDF 里单行等宽更可能是终端输出的一行或普通说明
_MIN_CODE_LINES = 2

# pymupdf 图片块的 ext → MIME（仅用于拼出语法正确的 Data URL；
# 真实类型由 image_service 用 Pillow 读字节判定，这里取不到也不会错）
_MIME_BY_EXT = {
    "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg",
    "gif": "image/gif", "bmp": "image/bmp", "tiff": "image/tiff",
    "webp": "image/webp", "jp2": "image/jp2", "jpx": "image/jp2",
}


class PdfParseError(Exception):
    """PDF 无法解析（文件损坏 / 格式不受支持 / 需要密码）—— 交给作业层记入失败清单。"""


class PdfEncryptedError(PdfParseError):
    """PDF 已加密且未提供密码。"""


def _append_image(blob: bytes, ext: str, images: list[ImageRef]) -> str:
    """登记一张图片并返回正文用的定位标记（字节走 Data URL，不落盘）。"""
    raw = _MARKER_TEMPLATE.format(seq=len(images) + 1)
    mime = _MIME_BY_EXT.get(ext.lower(), "image/png")
    images.append(
        ImageRef(
            raw=raw, start=-1, end=-1, alt="图片",
            target=f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}",
            kind="md",      # 正文里插入的就是标准 Markdown 图片语法
        )
    )
    return raw


def _image_marker(block: dict, images: list[ImageRef]) -> str:
    """把图片块登记为 ImageRef 并返回标记；块里没有可用字节时返回空串。

    type=1 的块自带 `image`（已解码字节）与 `ext`，扫描件的整页图也在其中 ——
    这正是「扫描件无需 OCR」的依据：它与 Word 内嵌图在数据结构上没有区别。
    """
    blob = block.get("image")
    if not blob:
        return ""
    return _append_image(blob, (block.get("ext") or "png"), images)


def _render_page_marker(page, images: list[ImageRef]) -> str:
    """整页渲染兜底：给「无文本层 + 取不到图片块」的页留一张图。

    纯色空白页直接放弃 —— 渲染出来只是一张白图，白白占用多模态调用额度。
    """
    try:
        pix = page.get_pixmap(dpi=_SCAN_RENDER_DPI)
    except Exception:  # noqa: BLE001 —— 渲染失败即放弃该页，不影响其余页
        return ""
    if getattr(pix, "is_unicolor", False):
        return ""
    # 优先 JPEG：整页 150 DPI 的 PNG 很容易超过 image_max_bytes，被下游整张丢弃
    for fmt, ext in (("jpeg", "jpeg"), ("png", "png")):
        try:
            blob = pix.tobytes(fmt)
        except Exception:  # noqa: BLE001 —— 该编码不受支持则换下一种
            continue
        if blob:
            return _append_image(blob, ext, images)
    return ""


def _line_text(line: dict) -> str:
    return "".join(span.get("text", "") for span in line.get("spans", []))


def _visible_spans(line: dict) -> list[dict]:
    return [span for span in line.get("spans", []) if span.get("text", "").strip()]


def _is_code_line(line: dict) -> bool:
    """整行可见文字都用等宽字体即为代码行。

    PDF 没有段落样式可看（不像 Word 有「HTML 预设格式」这类样式名），
    字体的等宽特征就是唯一线索：代码在 PDF 里必然被排成等宽字体。
    """
    spans = _visible_spans(line)
    return bool(spans) and all(is_mono_font(span.get("font", "")) for span in spans)


def _char_width(spans: list[dict]) -> float:
    """估算单个等宽字符的宽度：优先用实测宽度（span 宽 / 字符数），取不到再按字号回退。"""
    measured = [
        (span["bbox"][2] - span["bbox"][0]) / len(span["text"])
        for span in spans
        if span.get("text") and span.get("bbox")
    ]
    if measured:
        return min(measured)     # 混排全角字符会抬高比值，取最小值更接近单字符宽
    sizes = [span["size"] for span in spans if span.get("size")]
    return min(sizes) * _MONO_CHAR_RATIO if sizes else 0.0


def _fence_code(lines: list[tuple[float, str]], spans: list[dict]) -> str:
    """把连续的代码行合成围栏块。

    PDF 的缩进是**排版位置**而不是空格字符，提取出的文本一律左对齐，所以这里用各行的
    x0 相对代码块最左侧的偏移，除以字符宽换算回前导空格 —— 不还原则代码层级全丢。
    """
    left = min(x0 for x0, _ in lines)
    char_width = _char_width(spans)
    rendered = [
        " " * (round((x0 - left) / char_width) if char_width > 0 else 0) + text
        for x0, text in lines
    ]
    return fence_block("\n".join(rendered))


def _render_page(page, images: list[ImageRef]) -> tuple[str, bool]:
    """渲染一页，返回 (正文, 该页是否有文本层)。

    按块版面顺序拼文本与图片标记；整页既无文本又无可用图片块时走整页渲染兜底，
    此时「无文本层」的判定仍然成立（返回 False），扫描页因此能被计入 meta。

    代码行逐行判定并**跨块累积**：实测同一段代码会被 pymupdf 按缩进拆进不同块，
    只在块内合并会把一段代码切成两截。
    """
    blocks: list[str] = []
    has_text = False
    code_lines: list[tuple[float, str]] = []    # 累积中的连续代码行 (x0, 文本)
    code_spans: list[dict] = []                 # 估算字符宽用（还原缩进）

    def flush_code() -> None:
        if not code_lines:
            return
        lines = list(code_lines)
        spans = list(code_spans)
        code_lines.clear()
        code_spans.clear()
        if len(lines) < _MIN_CODE_LINES:
            blocks.extend(text for _, text in lines)   # 单行等宽：退回普通段落
            return
        blocks.append(_fence_code(lines, spans))

    for block in page.get_text("dict")["blocks"]:
        btype = block.get("type")
        if btype == 1:                      # 图片块（含扫描件的整页图）
            marker = _image_marker(block, images)
            if marker:
                flush_code()
                blocks.append(marker)
            continue
        if btype != 0:                      # 未知块类型，跳过
            continue
        # btype == 0：文本块

        plain: list[str] = []
        for line in block.get("lines", []):
            text = _line_text(line)
            if not text.strip():
                continue
            has_text = True
            if _is_code_line(line):
                if plain:                   # 顺序保持：先落普通行，再开代码缓冲
                    blocks.append("\n".join(plain))
                    plain = []
                code_lines.append((line["bbox"][0], text))
                code_spans.extend(_visible_spans(line))
            else:
                flush_code()
                plain.append(text)
        if plain:
            blocks.append("\n".join(plain))

    flush_code()
    body = "\n\n".join(blocks)
    if body.strip():
        return body, has_text
    return _render_page_marker(page, images), False


class PdfParser(DocumentParser):
    supported_exts = (".pdf",)

    def parse(self, path: Path) -> ParsedDocument:
        images: list[ImageRef] = []
        blocks: list[str] = []
        scanned = 0

        try:
            doc = pymupdf.open(str(path))
        except Exception as exc:  # noqa: BLE001 —— 损坏 / 非法 PDF：给出可读原因而非底层英文栈
            raise PdfParseError(
                f"PDF 打开失败（文件损坏或格式不受支持）：{path.name}"
            ) from exc

        with doc:
            if doc.needs_pass:
                raise PdfEncryptedError(
                    f"PDF 已加密，需先解除密码保护才能索引：{path.name}"
                )
            page_count = doc.page_count
            for page_no, page in enumerate(doc, start=1):
                body, has_text = _render_page(page, images)
                if not body.strip():
                    continue
                if not has_text:
                    scanned += 1
                if page_count > 1:
                    body = f"## 第 {page_no} 页\n\n{body}"
                blocks.append(body)

        content = "\n\n".join(blocks)
        # 回填标记位置：attach_images 靠 ref.raw 定位，偏移仅用于溯源展示
        for ref in images:
            ref.start = content.find(ref.raw)
            ref.end = ref.start + len(ref.raw)

        if scanned:
            logger.warning(
                "PDF 存在无文本层的页面（疑似扫描件），已按整页图片处理；"
                "未配置多模态 LLM 时这些页不会产出可检索文字",
                path=path.name, scanned_pages=scanned, total_pages=page_count,
            )

        return ParsedDocument(
            content=content,
            title=path.stem,
            mtime=os.path.getmtime(path),
            meta={
                "source_type": "pdf",
                "pages": page_count,
                "scanned": bool(scanned),
                "scanned_pages": scanned,
                "images": len(images),
            },
            images=images,
        )


register(PdfParser())
