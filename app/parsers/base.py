"""解析器·基类 — 多格式文件解析的抽象契约（docs/design.md §16.2）。

能力：
- 定义解析结果数据结构 ParsedDocument（纯文本 + 元数据）
- 定义解析器抽象基类 DocumentParser（按扩展名自注册）
- ParsedDocument.to_chunks(): 衔接 chunker，一键完成解析→分块
- parse_file(path): 便捷函数，按扩展名自动路由到已注册 parser
- 与 RAG 管线解耦：任何新格式只需新增一个 parser，不动 chunker / embedder

主要类：
- @dataclass ParsedDocument: content / title / mtime / meta / to_chunks()
- class DocumentParser(ABC): supported_exts / parse()
- normalize_ext(ext): 扩展名规范化（'MD' / 'md' / '.md' → '.md'）
- parse_file(path): 按扩展名取 parser 并解析，未注册返回 None

关联方案：docs/design.md §16（多格式文件与过滤设计）。
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.rag.chunker import Chunk


# 等宽字体补充名单（规范化掉空格 / 连字符后精确比较）
_MONO_EXACT = frozenset({
    "monaco", "menlo", "hack", "inconsolata", "fira", "cascadiacode",
    "sourcecodepro", "lucidaconsole", "andale", "ptmono",
})


def is_mono_font(name: str) -> bool:
    """字体名是否等宽 —— docx（run 字体）与 pdf（span 字体）共用同一判据。

    规范化掉空格 / 连字符后按「mono 结尾 + 补充名单 + 关键词」判断：
    `endswith("mono")` 而非 `in` —— 等宽字体几乎都以 Mono 收尾（JetBrains Mono、
    DejaVu Sans Mono…），而 `in` 会把 "Monotype Corsiva" 这类比例字体误判成等宽。
    """
    normalized = re.sub(r"[\s\-_]", "", name.lower())
    if not normalized:
        return False
    return (
        normalized.endswith("mono")
        or normalized in _MONO_EXACT
        or "consol" in normalized          # Consolas / Inconsolata
        or normalized.startswith("courier")
    )


def fence_block(body: str) -> str:
    """把正文包成 Markdown 围栏代码块；正文自带 ``` 时换 ~~~ 围栏，避免提前闭合。"""
    marker = "~~~" if "```" in body else "```"
    return f"{marker}\n{body}\n{marker}"


@dataclass
class ImageRef:
    """文档中出现的一处图片引用（解析层输出，供 image_service 处理）。

    - raw:     原文中的完整片段（回插时按它做替换）
    - start:   在 content 中的起始偏移
    - end:     在 content 中的结束偏移（不含）
    - alt:     替代文本（Markdown 语法里的 alt，可能为空）
    - target:  图片目标：http/https URL 或本地路径（相对 md 文件 / Obsidian wikilink 裸名）
    - kind:    "md"=标准 Markdown 语法；"wiki"=Obsidian wikilink
    """

    raw: str
    start: int
    end: int
    alt: str
    target: str
    kind: str = "md"


@dataclass
class ParsedDocument:
    """单文件解析结果。

    - content: 纯文本（已是待分块的原始文本，不含二进制 / 样式）
    - title:   标题（文件名或文档内标题）
    - mtime:   修改时间（秒级浮点，用于增量索引）
    - meta:    可选元数据（页数 / sheet 名 / 来源类型等），后续可写入 Chroma metadata 做过滤
    - images:  文档中出现的图片引用列表（按位置排序），由 image_service 处理后再切分
    """

    content: str
    title: str
    mtime: float
    meta: dict = field(default_factory=dict)
    images: list["ImageRef"] = field(default_factory=list)

    def to_chunks(
        self,
        fmt: str = "text",
        max_chars: int = 800,
        overlap: bool = True,
    ) -> list["Chunk"]:
        """衔接 chunker：把解析后的纯文本切分为 Chunk 列表。

        Args:
            fmt: 文档格式（markdown / html / text），决定切分策略
            max_chars: 每个片段最大字符数
            overlap: 是否保留片段间重叠
        Returns:
            Chunk 列表，metadata 含 chunk_index / char_start / char_end / breadcrumb 等
        """
        from app.rag.chunker import split

        return split(
            self.content,
            fmt=fmt,
            max_chars=max_chars,
            overlap=overlap,
            extra_metadata=self.meta,
        )


class DocumentParser(ABC):
    """文件解析器抽象基类。

    子类需声明 supported_exts（小写扩展名元组，如 (".md",)），
    并实现 parse() 返回 ParsedDocument。模块 import 时调用 registry.register(self) 自注册。
    """

    supported_exts: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument:
        """解析单个文件，返回纯文本 + 元数据。"""
        ...


def normalize_ext(ext: str) -> str:
    """规范扩展名：统一小写、带前导点（'MD' / 'md' / '.md' → '.md'）。"""
    ext = ext.lower()
    return ext if ext.startswith(".") else f".{ext}"


def parse_file(path: Path) -> ParsedDocument | None:
    """便捷函数：按扩展名自动路由到已注册 parser 并解析。

    未注册的扩展名（未知格式或可选依赖未安装）返回 None。
    """
    from app.parsers.registry import get_parser

    parser = get_parser(path.suffix)
    if parser is None:
        return None
    return parser.parse(path)
