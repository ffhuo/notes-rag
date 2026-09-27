"""PDF 解析器 — 正文提取、页码小节、扫描件（整页图）与加密 PDF 的降级行为。

关注点：
- 正文按块版面顺序输出；多页 PDF 以 `## 第 N 页` 分节（切分因此能按页切段）
- 扫描页 = 一个整页图片块 → 产出 ImageRef（短标记 + Data URL），
  与 Word 内嵌图共用 image_service 的 data: 分支，无需 OCR 引擎
- 无文本层且无图片块（纯矢量）的页整页渲染兜底；纯空白页必须放弃（否则白图白占调用）
- 加密 PDF 抛 PdfEncryptedError，由作业层记入失败清单而不是让整个作业崩掉

样本全部在 tmp_path 里**动态生成**（pymupdf + Pillow），不往仓库塞二进制。

关联方案：docs/design.md §16；图片方案见 image-progress 约定。
"""
import base64
import io
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from app.parsers.pdf import PdfEncryptedError, PdfParseError, PdfParser
from app.services import image_service


def _png_bytes(width: int = 400, height: int = 600, color=(30, 90, 180)) -> bytes:
    """造一张纯色 PNG（默认远大于 image_min_width / height 门槛）。"""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _make_pdf(tmp_path: Path, pages: list[str], name: str = "sample.pdf") -> Path:
    """按页类型生成 PDF：'text'=文字页，'image'=整页图（扫描件），
    'vector'=纯矢量绘制页，'blank'=纯空白页。"""
    doc = pymupdf.open()
    for kind in pages:
        page = doc.new_page()
        if kind == "text":
            page.insert_text((72, 100), "Hello page")
        elif kind == "image":
            page.insert_image(pymupdf.Rect(0, 0, 400, 600), stream=_png_bytes())
        elif kind == "vector":
            page.draw_rect(pymupdf.Rect(100, 100, 300, 300), color=(1, 0, 0), fill=(1, 0, 0))
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def _decode(ref) -> bytes:
    assert ref.target.startswith("data:")
    return base64.b64decode(ref.target.split(",", 1)[1])


def _make_code_pdf(
    tmp_path: Path, lines: list[tuple[float, str]], name: str = "code.pdf"
) -> Path:
    """生成一页 PDF：按 (x 坐标, 文本) 逐行以 Courier 排版。

    缩进刻意用 x 坐标表达（真实 PDF 就是这样，字符里没有前导空格）。
    """
    doc = pymupdf.open()
    page = doc.new_page()
    for i, (x, text) in enumerate(lines):
        page.insert_text((x, 100 + i * 16), text, fontname="cour", fontsize=11)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def test_parse_text_page(tmp_path):
    parsed = PdfParser().parse(_make_pdf(tmp_path, ["text"]))

    assert "Hello page" in parsed.content
    assert parsed.title == "sample"
    assert parsed.meta["source_type"] == "pdf"
    assert parsed.meta["pages"] == 1
    # 单页不加页码标题：加了一层无信息的 `## 第 1 页` 只会污染正文
    assert "第 1 页" not in parsed.content
    assert parsed.images == []


def test_registered_for_pdf_extension():
    """注册必须生效：否则扫描到 .pdf 也会被静默跳过（缺依赖时正是这种表现）。"""
    from app.parsers import registry

    assert isinstance(registry.get_parser(".pdf"), PdfParser)


def test_multi_page_uses_page_heading(tmp_path):
    parsed = PdfParser().parse(_make_pdf(tmp_path, ["text", "text"]))

    assert "## 第 1 页" in parsed.content
    assert "## 第 2 页" in parsed.content
    assert parsed.content.index("第 1 页") < parsed.content.index("第 2 页")
    # 页码标题是 markdown 小节 → 切分后成为 chunk 边界与面包屑
    chunks = parsed.to_chunks(fmt="markdown", max_chars=2000)
    assert any("第 2 页" in chunk.metadata.get("breadcrumb", "") for chunk in chunks)


def test_scanned_page_becomes_image_ref(tmp_path):
    """扫描页：结构上就是一个整页图片块 → 产出 ImageRef，不需要 OCR。"""
    parsed = PdfParser().parse(_make_pdf(tmp_path, ["text", "image"]))

    assert len(parsed.images) == 1
    ref = parsed.images[0]
    # 正文里留的是短标记（不是整段 base64），锚点必须与偏移自洽
    assert ref.raw in parsed.content
    assert parsed.content[ref.start : ref.end] == ref.raw
    assert Image.open(io.BytesIO(_decode(ref))).size == (400, 600)
    # 扫描页计入 meta，供上层提示「这些页需要多模态 LLM 才能检索」
    assert parsed.meta["scanned"] is True
    assert parsed.meta["scanned_pages"] == 1
    assert parsed.meta["images"] == 1


def test_blank_page_produces_nothing(tmp_path):
    """纯空白页必须放弃：渲染出来只是一张白图，白白占用多模态调用额度。"""
    parsed = PdfParser().parse(_make_pdf(tmp_path, ["blank"]))

    assert parsed.content.strip() == ""
    assert parsed.images == []
    assert parsed.meta["scanned_pages"] == 0


def test_vector_only_page_rendered_as_fallback(tmp_path):
    """无文本层又无图片块（纯矢量绘制页）：整页渲染兜底，否则该页彻底丢失。"""
    parsed = PdfParser().parse(_make_pdf(tmp_path, ["vector"]))

    assert len(parsed.images) == 1
    assert Image.open(io.BytesIO(_decode(parsed.images[0]))).format == "JPEG"
    assert parsed.meta["scanned_pages"] == 1


def test_encrypted_pdf_raises_readable_error(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "secret")
    path = tmp_path / "enc.pdf"
    doc.save(str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256,
             owner_pw="owner", user_pw="user")
    doc.close()

    with pytest.raises(PdfEncryptedError) as exc:
        PdfParser().parse(path)

    assert "加密" in str(exc.value)          # 失败清单里要给用户看得懂的原因
    assert isinstance(exc.value, PdfParseError)


def test_broken_pdf_raises_readable_error(tmp_path):
    """损坏文件不能把 pymupdf 的英文报错直接抛给作业层。"""
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not a pdf at all")

    with pytest.raises(PdfParseError) as exc:
        PdfParser().parse(path)

    assert "打开失败" in str(exc.value)


def test_scanned_pdf_chunks_are_all_image_shells(tmp_path):
    """纯扫描件每页只剩图片标记 → 一律判为空壳，ingest 不会把它们写进索引。

    否则检索会召回一堆无信息量的命中（正文只有 `![图片](pdf-image:N)`）。
    """
    from app.services.ingest_service import _is_image_shell

    parsed = PdfParser().parse(_make_pdf(tmp_path, ["image"] * 3))
    chunks = parsed.to_chunks(fmt="markdown")

    assert chunks
    assert all(_is_image_shell(chunk) for chunk in chunks)


def test_image_shell_judgement():
    """判据三分：只剩标记=空壳；标记夹着文字=保留；纯文字=保留。"""
    from app.rag.chunker import Chunk
    from app.services.ingest_service import _is_image_shell

    shell = Chunk(text="[第 1 页]\n![图片](pdf-image:1)", metadata={"breadcrumb": "第 1 页"})
    mixed = Chunk(
        text="[第 1 页]\n图上方文字\n\n![图片](pdf-image:1)\n\n图下方文字",
        metadata={"breadcrumb": "第 1 页"},
    )
    plain = Chunk(text="只有文字", metadata={})

    assert _is_image_shell(shell)
    assert not _is_image_shell(mixed)
    assert not _is_image_shell(plain)


def test_image_marker_survives_chunking(tmp_path):
    """切分后标记仍完整落在某个 chunk 里 —— attach_images 靠 ref.raw 定位，断了就回填不了。"""
    parsed = PdfParser().parse(_make_pdf(tmp_path, ["image"]))
    chunks = parsed.to_chunks(fmt="markdown", max_chars=2000)

    assert any(ref.raw in chunk.text for chunk in chunks for ref in parsed.images)


def test_mono_lines_become_fence(tmp_path):
    """连续等宽行合并成一个围栏代码块，行间不插空行（否则代码被拆成多段）。"""
    parsed = PdfParser().parse(
        _make_code_pdf(
            tmp_path,
            [(72, "def hello():"), (88, "print('hi')"), (88, "return 1")],
        )
    )

    assert parsed.content.count("```") == 2      # 围栏成对，不存在半截围栏
    body = parsed.content.split("```")[1]
    assert "\n\n" not in body.strip("\n")        # 代码行之间不能被空行隔开
    lines = body.strip("\n").splitlines()
    assert lines[0] == "def hello():"
    # 缩进由 x 坐标还原：后两行同样靠右，缩进量必须相等且大于 0
    assert _indent(lines[1]) == _indent(lines[2]) > 0
    assert lines[1].strip() == "print('hi')"
    assert lines[2].strip() == "return 1"


def test_code_and_text_lines_split_by_font(tmp_path):
    """同一页内等宽行与非等宽行分流：代码进围栏，正文留在围栏外。"""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Below is a code sample:")
    page.insert_text((72, 130), "def hello():", fontname="cour", fontsize=11)
    page.insert_text((88, 146), "print('hi')", fontname="cour", fontsize=11)
    page.insert_text((72, 180), "That is all.")
    path = tmp_path / "mixed.pdf"
    doc.save(str(path))
    doc.close()

    content = PdfParser().parse(path).content

    assert content.count("```") == 2
    fenced = content.split("```")[1]
    assert "def hello():" in fenced and "print('hi')" in fenced
    assert "code sample" not in fenced and "That is all" not in fenced
    assert content.startswith("Below is a code sample:")
    assert content.rstrip().endswith("That is all.")


def test_single_mono_line_not_fenced(tmp_path):
    """单行等宽不升级为代码块（与 docx 同一阈值），退回普通段落。"""
    parsed = PdfParser().parse(_make_code_pdf(tmp_path, [(72, "print('hi')")]))

    assert "```" not in parsed.content
    assert "print('hi')" in parsed.content


@pytest.mark.asyncio
async def test_scanned_image_uses_local_image_standard(tmp_path):
    """扫描页的整页图与本地图 / Word 内嵌图共用校验标准，按原始字节内容寻址。"""
    parsed = PdfParser().parse(_make_pdf(tmp_path, ["image"]))
    ref = parsed.images[0]

    prepared = await image_service.prepare(ref, tmp_path, tmp_path)

    assert prepared.ok
    assert prepared.source_kind == "embedded"     # 字节在手，不是远程外链
    assert prepared.content_key == image_service._sha256_hex(_decode(ref))
    assert (prepared.width, prepared.height) == (400, 600)
