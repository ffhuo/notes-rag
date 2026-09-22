"""解析器·基类 — 多格式文件解析的抽象契约（docs/design.md §16.2）。

能力：
- 定义解析结果数据结构 ParsedDocument（纯文本 + 元数据）
- 定义解析器抽象基类 DocumentParser（按扩展名自注册）
- 与 RAG 管线解耦：任何新格式只需新增一个 parser，不动 chunker / embedder

主要类：
- @dataclass ParsedDocument: content / title / mtime / meta
- class DocumentParser(ABC): supported_exts / parse()
- normalize_ext(ext): 扩展名规范化（'MD' / 'md' / '.md' → '.md'）

关联方案：docs/design.md §16（多格式文件与过滤设计）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedDocument:
    """单文件解析结果。

    - content: 纯文本（已是待分块的原始文本，不含二进制 / 样式）
    - title:   标题（文件名或文档内标题）
    - mtime:   修改时间（秒级浮点，用于增量索引）
    - meta:    可选元数据（页数 / sheet 名 / 来源类型等），后续可写入 Chroma metadata 做过滤
    """

    content: str
    title: str
    mtime: float
    meta: dict = field(default_factory=dict)


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
