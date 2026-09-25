"""RAG·分块 — 把文档切分为合适长度的片段（多格式通用，docs/design.md §7 / §16）。

统一入口 split() 根据格式选择切分策略：
- markdown / html：按标题层级切分，保留面包屑（breadcrumb）上下文前缀
- text（txt / pdf / docx / xlsx 等纯文本）：递归字符切分，逐级降级分隔符

每个 Chunk 携带 metadata，供向量库与业务层使用：
- splitter 产出：chunk_index, char_start, char_end, breadcrumb, heading
- parser 补充：page, line_start, line_end（通过 extra_metadata 传入）
- ingest 补充：source_file, vault_id, note_id, tags, timestamp（直接操作 Chunk.metadata）

主要类型/函数：
- @dataclass Chunk: text + metadata
- split(text, fmt, max_chars, overlap, extra_metadata) -> list[Chunk]: 统一入口
- split_markdown(text, max_chars, extra_metadata) -> list[Chunk]
- split_html(text, max_chars, extra_metadata) -> list[Chunk]
- split_text(text, max_chars, overlap, extra_metadata) -> list[Chunk]

关联方案：docs/design.md §7（RAG 管线设计·分块）、§16（多格式与过滤）。
"""

import re
from dataclasses import dataclass, field
from typing import Any

# ===== 格式常量 =====

FORMAT_MARKDOWN = "markdown"
FORMAT_HTML = "html"
FORMAT_TEXT = "text"

# ===== 正则 =====

# Markdown 标题：# ~ ######
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
# HTML 标题：<h1>~<h6>（含属性）
_HTML_HEADING_RE = re.compile(
    r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL
)
# HTML 标签清理
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# HTML 实体（常见）
_HTML_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|#39|nbsp);")

# Markdown pipe table：连续行以 | 开头，至少含表头分隔行
# 匹配：表头行 + 分隔行(|---|---|) + 至少一行数据
_MD_TABLE_RE = re.compile(
    r"((?:^[ \t]*\|[^\n]+\|[ \t]*\n)"  # 表头行
    r"(?:^[ \t]*\|[ \t]*[-:]+[-: |]*\|[ \t]*\n)"  # 分隔行
    r"(?:^[ \t]*\|[^\n]+\|[ \t]*\n?)+)",  # 数据行（至少一行）
    re.MULTILINE,
)
# HTML <table>...</table>
_HTML_TABLE_RE = re.compile(
    r"<table[^>]*>.*?</table>", re.IGNORECASE | re.DOTALL
)

# 递归切分分隔符优先级（从大到小）
_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ". ", "! ", "? ", "；", ";", "，", ",", " ", ""]

# 滑动窗口重叠比例
_OVERLAP_RATIO = 0.15


# ===== Chunk 数据模型 =====


@dataclass
class Chunk:
    """分块结果，携带文本与元数据。

    metadata 由各阶段补充：
    - splitter: chunk_index, char_start, char_end, breadcrumb, heading
    - parser: page, line_start, line_end（经 extra_metadata 传入）
    - ingest: source_file, source_format, vault_id, note_id, tags, timestamp
      （ingest_service 直接操作 chunk.metadata）

    ChromaDB 约束：metadata 值必须为基本类型（str/int/float/bool/None）。
    若需存 list/dict（如 tags），ingest 层应 JSON 序列化为字符串。
    """

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ===== 统一入口 =====


def split(
    text: str,
    fmt: str = FORMAT_TEXT,
    max_chars: int = 800,
    overlap: bool = True,
    extra_metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """统一分块入口，根据格式选择策略。

    Args:
        text: 待切分文本（已提取为纯文本，HTML 需预处理去标签或走 html 策略）
        fmt: 文档格式，markdown / html / text
        max_chars: 每个片段最大字符数
        overlap: 是否在切分时保留片段间重叠（上下文连续性）
        extra_metadata: parser 产出的额外元数据（page / line_start / line_end 等），
                        会被合并到每个 Chunk.metadata 中
    """
    if not text or not text.strip():
        return []

    if fmt == FORMAT_MARKDOWN:
        return split_markdown(text, max_chars, extra_metadata)
    elif fmt == FORMAT_HTML:
        return split_html(text, max_chars, extra_metadata)
    else:
        return split_text(text, max_chars, overlap=overlap, extra_metadata=extra_metadata)


# ===== Markdown 策略：标题层级切分 =====


def split_markdown(
    text: str,
    max_chars: int = 800,
    extra_metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """按 Markdown 标题层级切分，保留标题面包屑作为上下文前缀。

    每个 Chunk.metadata 包含：
    - chunk_index: 全文内的序号
    - breadcrumb: 标题路径（如 "第一章 > 第一节"）
    - heading: 当前节最近的标题文本
    - char_start / char_end: 在原文中的字符偏移
    - extra_metadata 中的所有字段
    """
    if not text or not text.strip():
        return []

    headings = list(_MD_HEADING_RE.finditer(text))
    if not headings:
        return split_text(text, max_chars, extra_metadata=extra_metadata)

    sections = _extract_sections(text, headings, _md_heading_level, _md_heading_title)
    if not sections:
        return split_text(text, max_chars, extra_metadata=extra_metadata)

    breadcrumbs = _build_breadcrumbs(sections)
    chunks: list[Chunk] = []
    chunk_index = 0

    for (level, title, body), breadcrumb in zip(sections, breadcrumbs):
        # 去掉标题行，获取纯正文 + 正文在原文中的偏移
        body_clean, body_offset = _strip_headings_get_offset(body, headings, text)
        if not body_clean.strip():
            continue

        prefix = f"[{breadcrumb}]\n" if breadcrumb else ""
        effective_max = max_chars - len(prefix)
        if effective_max <= 0:
            chunks.append(_make_chunk(
                prefix + body_clean, chunk_index, 0, len(body_clean),
                breadcrumb, title, extra_metadata,
            ))
            chunk_index += 1
            continue

        for piece, p_start, p_end in _split_with_table_protection(
            body_clean, effective_max, _MD_TABLE_RE, base_offset=body_offset
        ):
            if piece.strip():
                chunks.append(_make_chunk(
                    prefix + piece, chunk_index, p_start, p_end,
                    breadcrumb, title, extra_metadata,
                ))
                chunk_index += 1

    return chunks


# ===== HTML 策略：标题切分 =====


def split_html(
    text: str,
    max_chars: int = 800,
    extra_metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """按 HTML 标题（h1~h6）切分，保留面包屑前缀。

    与 Markdown 策略类似，但从 <hN> 标签提取标题层级。
    切分前自动去标签、反转义。
    """
    if not text or not text.strip():
        return []

    headings = list(_HTML_HEADING_RE.finditer(text))
    if not headings:
        plain = _strip_html(_HTML_TABLE_RE.sub(_html_table_to_markdown, text))
        return split_text(plain, max_chars, extra_metadata=extra_metadata)

    sections = _extract_sections(text, headings, _html_heading_level, _html_heading_title)
    if not sections:
        plain = _strip_html(_HTML_TABLE_RE.sub(_html_table_to_markdown, text))
        return split_text(plain, max_chars, extra_metadata=extra_metadata)

    breadcrumbs = _build_breadcrumbs(sections)
    chunks: list[Chunk] = []
    chunk_index = 0

    for (level, title, body), breadcrumb in zip(sections, breadcrumbs):
        # 先把 HTML 表格转为 Markdown pipe table 格式，再做标签清理
        body_converted = _HTML_TABLE_RE.sub(_html_table_to_markdown, body)
        body_plain = _strip_html(body_converted).strip()
        if not body_plain:
            continue

        prefix = f"[{breadcrumb}]\n" if breadcrumb else ""
        effective_max = max_chars - len(prefix)
        if effective_max <= 0:
            chunks.append(_make_chunk(
                prefix + body_plain, chunk_index, 0, len(body_plain),
                breadcrumb, title, extra_metadata,
            ))
            chunk_index += 1
            continue

        for piece, p_start, p_end in _split_with_table_protection(
            body_plain, effective_max, _MD_TABLE_RE
        ):
            if piece.strip():
                chunks.append(_make_chunk(
                    prefix + piece, chunk_index, p_start, p_end,
                    breadcrumb, title, extra_metadata,
                ))
                chunk_index += 1

    return chunks


# ===== Text 策略：递归字符切分 =====


def split_text(
    text: str,
    max_chars: int = 800,
    overlap: bool = True,
    extra_metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """递归字符切分（txt / pdf / docx / xlsx 等纯文本）。

    每个 Chunk.metadata 包含：
    - chunk_index, char_start, char_end
    - extra_metadata 中的所有字段
    """
    if not text or not text.strip():
        return []

    text = text.strip()
    if len(text) <= max_chars:
        return [_make_chunk(text, 0, 0, len(text), "", "", extra_metadata)]

    chunks: list[Chunk] = []
    for i, (piece, start, end) in enumerate(
        _split_recursive_with_offset(text, max_chars, overlap=overlap)
    ):
        if piece.strip():
            chunks.append(_make_chunk(piece, i, start, end, "", "", extra_metadata))
    return chunks


# ===== 内部：表格保护切分 =====


def _split_with_table_protection(
    text: str,
    max_chars: int,
    table_re: re.Pattern,
    base_offset: int = 0,
) -> list[tuple[str, int, int]]:
    """表格保护切分：先提取表格，再对非表格文本递归切分，最后合并。

    策略：
    1. 用 table_re 找出所有表格区块
    2. 把表格替换为占位符（长度一致），对非表格文本递归切分
    3. 切分完成后，把占位符替换回表格原文
    4. 若单个表格 > max_chars，按行切分，每个子表重复表头行
    """
    if not text.strip():
        return []

    # 找出所有表格
    tables = list(table_re.finditer(text))
    if not tables:
        return _split_recursive_with_offset(text, max_chars, base_offset=base_offset)

    # 提取非表格文本段（表格区间跳过）
    non_table_segments: list[tuple[str, int]] = []  # (text, offset)
    cursor = 0

    for i, m in enumerate(tables):
        # 表格前的非表格文本
        if m.start() > cursor:
            segment = text[cursor : m.start()]
            non_table_segments.append((segment, cursor))
        cursor = m.end()

    # 最后一段非表格文本
    if cursor < len(text):
        segment = text[cursor:]
        non_table_segments.append((segment, cursor))

    # 对非表格文本逐段递归切分
    results: list[tuple[str, int, int]] = []
    for segment, offset in non_table_segments:
        seg_results = _split_recursive_with_offset(
            segment, max_chars, base_offset=base_offset + offset
        )
        results.extend(seg_results)

    # 如果没有非表格文本（全是表格），直接处理表格
    if not results:
        for i, m in enumerate(tables):
            table_text = m.group()
            table_offset = m.start()
            table_chunks = _split_table(table_text, max_chars, table_offset)
            results.extend(table_chunks)
        return results

    # 检查每个结果 chunk 中是否需要插入表格
    # 当前策略：表格作为独立 chunk 追加（不与文本合并，避免混排）
    for i, m in enumerate(tables):
        table_text = m.group()
        table_offset = m.start()
        table_chunks = _split_table(table_text, max_chars, table_offset)
        # 在合适的位置插入表格 chunk（按 offset 顺序）
        results.extend(table_chunks)

    # 按 char_start 排序
    results.sort(key=lambda x: x[1])

    return results


def _split_table(
    table_text: str,
    max_chars: int,
    base_offset: int = 0,
) -> list[tuple[str, int, int]]:
    """拆分大表格：按行切分，每个子表重复表头行。

    Markdown table 和 HTML table 通用：
    - 第 1 行为表头，提取后保留
    - 后续行按累加到 max_chars 切分，每个子表都带上表头
    """
    if len(table_text) <= max_chars:
        return [(table_text, base_offset, base_offset + len(table_text))]

    lines = table_text.split("\n")
    if len(lines) < 3:
        # 不够构成表格，直接返回
        return [(table_text, base_offset, base_offset + len(table_text))]

    # 第 1 行为表头，第 2 行为分隔行（Markdown）或 thead（HTML）
    header = lines[0] + "\n" + lines[1] + "\n"
    data_lines = lines[2:]

    chunks: list[tuple[str, int, int]] = []
    current = header
    current_start = base_offset

    line_offset = base_offset + len(lines[0]) + 1 + len(lines[1]) + 1  # header 两行 + 换行

    for line in data_lines:
        line_with_nl = line + "\n" if line.strip() else "\n"
        if len(current) + len(line_with_nl) <= max_chars:
            current += line_with_nl
        else:
            if len(current) > len(header):
                chunks.append((current.rstrip("\n"), current_start, current_start + len(current.rstrip("\n"))))
            # 新子表：重复表头
            current = header + line_with_nl
            current_start = line_offset
        line_offset += len(line) + 1  # +1 for \n

    if len(current) > len(header):
        chunks.append((current.rstrip("\n"), current_start, current_start + len(current.rstrip("\n"))))

    return chunks if chunks else [(table_text, base_offset, base_offset + len(table_text))]


# ===== 内部：带偏移的递归切分 =====


def _split_recursive_with_offset(
    text: str,
    max_chars: int,
    separators: list[str] | None = None,
    overlap: bool = True,
    base_offset: int = 0,
) -> list[tuple[str, int, int]]:
    """递归字符切分，返回 (chunk_text, char_start, char_end)。

    char_start/char_end 是相对于最原始文本的偏移（base_offset 为 0 时）。
    """
    if separators is None:
        separators = _SEPARATORS

    if len(text) <= max_chars:
        return [(text, base_offset, base_offset + len(text))]

    for i, sep in enumerate(separators):
        if sep == "":
            break
        parts = text.split(sep)
        if len(parts) <= 1:
            continue

        # 递归处理各部分，追踪偏移
        sub_chunks: list[tuple[str, int, int]] = []
        offset = base_offset
        for part in parts:
            if len(part) > max_chars:
                sub_chunks.extend(
                    _split_recursive_with_offset(
                        part, max_chars, separators[i + 1:], overlap, offset
                    )
                )
            elif part.strip():
                sub_chunks.append((part, offset, offset + len(part)))
            # 累加偏移：当前部分 + 分隔符
            offset += len(part) + len(sep)

        if not sub_chunks:
            continue

        return _merge_chunks_with_offset(sub_chunks, max_chars, sep, overlap)

    # 硬切
    return _hard_split_with_offset(text, max_chars, overlap, base_offset)


def _merge_chunks_with_offset(
    chunks: list[tuple[str, int, int]],
    max_chars: int,
    sep: str,
    overlap: bool,
) -> list[tuple[str, int, int]]:
    """合并小片段到 max_chars 上限，保留偏移信息。"""
    if not chunks:
        return []

    overlap_size = int(max_chars * _OVERLAP_RATIO) if overlap else 0
    merged: list[tuple[str, int, int]] = []
    current_text = ""
    current_start = 0
    current_end = 0

    for text, start, end in chunks:
        if not text.strip():
            continue
        candidate = current_text + sep + text if current_text else text
        if len(candidate) <= max_chars:
            if not current_text:
                current_start = start
            current_text = candidate
            current_end = end
        else:
            if current_text:
                merged.append((current_text, current_start, current_end))
            # overlap：从上一个片段尾部取一段
            if overlap_size > 0 and merged:
                prev_text, prev_start, prev_end = merged[-1]
                tail = prev_text[-overlap_size:]
                current_text = tail + sep + text
                # tail 来自前一个 chunk 末尾，start 指向 tail 起点的近似位置
                current_start = max(prev_end - overlap_size, prev_start)
                current_end = end
            else:
                current_text = text
                current_start = start
                current_end = end

    if current_text:
        merged.append((current_text, current_start, current_end))

    return merged


def _hard_split_with_offset(
    text: str,
    max_chars: int,
    overlap: bool = True,
    base_offset: int = 0,
) -> list[tuple[str, int, int]]:
    """硬切，保留偏移。"""
    overlap_size = int(max_chars * _OVERLAP_RATIO) if overlap else 0
    step = max_chars - overlap_size
    if step <= 0:
        step = max_chars

    chunks: list[tuple[str, int, int]] = []
    for i in range(0, len(text), step):
        piece = text[i : i + max_chars]
        if piece.strip():
            chunks.append((piece, base_offset + i, base_offset + i + len(piece)))
    return chunks


# ===== Chunk 构造工具 =====


def _make_chunk(
    text: str,
    chunk_index: int,
    char_start: int,
    char_end: int,
    breadcrumb: str,
    heading: str,
    extra_metadata: dict[str, Any] | None,
) -> Chunk:
    """构造 Chunk，合并 splitter 元数据与 extra_metadata。"""
    meta: dict[str, Any] = {
        "chunk_index": chunk_index,
        "char_start": char_start,
        "char_end": char_end,
    }
    if breadcrumb:
        meta["breadcrumb"] = breadcrumb
    if heading:
        meta["heading"] = heading
    if extra_metadata:
        meta.update(extra_metadata)
    return Chunk(text=text, metadata=meta)


# ===== 标题切分通用工具 =====

HeadingMatch = re.Match  # 类型别名


def _extract_sections(
    text: str,
    headings: list[HeadingMatch],
    level_fn,
    title_fn,
) -> list[tuple[int, str, str]]:
    """从标题 match 列表中提取 (level, title, section_body) 列表。"""
    sections: list[tuple[int, str, str]] = []

    # 标题前的内容
    if headings[0].start() > 0:
        prefix = text[: headings[0].start()].strip()
        if prefix:
            sections.append((0, "", prefix))

    for i, match in enumerate(headings):
        level = level_fn(match)
        title = title_fn(match).strip()
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((level, title, body))

    return sections


def _build_breadcrumbs(
    sections: list[tuple[int, str, str]],
) -> list[str]:
    """根据标题层级构建面包屑路径列表。"""
    breadcrumbs: list[str] = []
    stack: list[tuple[int, str]] = []

    for level, title, _ in sections:
        if level == 0:
            breadcrumbs.append("")
            continue
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        breadcrumbs.append(" > ".join(t for _, t in stack))

    return breadcrumbs


def _strip_headings_get_offset(
    section_body: str,
    _headings: list[HeadingMatch],
    full_text: str,
) -> tuple[str, int]:
    """去掉 section 中的标题行，返回 (纯正文, 正文在原文中的起始偏移)。

    用于 Markdown：section body 包含标题行，去掉后正文从标题行之后开始。
    """
    # 找到第一个非标题行的位置
    cleaned = _MD_HEADING_RE.sub("", section_body)
    # 计算正文在 full_text 中的偏移
    # section_body 是 full_text 的子串（strip 后），先找 section 在原文的位置
    # 简化：用 cleaned 的第一个非空字符在 section_body 中的位置来推算
    leading_match = _MD_HEADING_RE.match(section_body)
    if leading_match:
        # 标题行长度（含换行）
        heading_line_end = section_body.find("\n", leading_match.end())
        if heading_line_end == -1:
            return cleaned.strip(), 0
        body_offset_in_section = heading_line_end + 1
        # section 在 full_text 中的位置
        section_start = full_text.find(section_body)
        if section_start == -1:
            return cleaned.strip(), 0
        return cleaned.strip(), section_start + body_offset_in_section
    return cleaned.strip(), 0


# ===== Markdown 标题工具 =====


def _md_heading_level(match: HeadingMatch) -> int:
    return len(match.group(1))


def _md_heading_title(match: HeadingMatch) -> str:
    return match.group(2)


# ===== HTML 标题工具 =====


def _html_heading_level(match: HeadingMatch) -> int:
    return int(match.group(1))


def _html_heading_title(match: HeadingMatch) -> str:
    return _strip_html(match.group(2))


def _strip_html(text: str) -> str:
    """去 HTML 标签 + 反转义常见实体。"""
    text = _HTML_TAG_RE.sub("", text)
    text = _HTML_ENTITY_RE.sub(
        lambda m: {
            "&amp;": "&",
            "&lt;": "<",
            "&gt;": ">",
            "&quot;": '"',
            "&#39;": "'",
            "&nbsp;": " ",
        }.get(m.group(), m.group()),
        text,
    )
    return text


# HTML 行正则
_HTML_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_HTML_TH_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.IGNORECASE | re.DOTALL)


def _html_table_to_markdown(match: re.Match) -> str:
    """把 HTML <table> 转为 Markdown pipe table 格式，供表格保护逻辑识别。

    策略：提取 <tr> 行，每行提取 <th>/<td> 单元格，生成 | A | B | 格式。
    第一行若含 <th>，视为表头并补一个分隔行 |---|---|。
    """
    html = match.group(0)
    rows = _HTML_TR_RE.findall(html)
    if not rows:
        return _strip_html(html)

    md_rows: list[list[str]] = []
    has_header = False

    for row_html in rows:
        cells = [c.strip() for c in _HTML_TH_RE.findall(row_html)]
        if not cells:
            # 无 <th>/<td>，可能为空行
            continue
        # 检测是否为表头行
        if "<th" in row_html.lower() and not has_header:
            has_header = True
        md_rows.append(cells)

    if not md_rows:
        return _strip_html(html)

    lines: list[str] = []
    for i, cells in enumerate(md_rows):
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0 and has_header:
            lines.append("|" + "|".join(["---"] * len(cells)) + "|")

    return "\n" + "\n".join(lines) + "\n"
