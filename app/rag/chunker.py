"""RAG·分块 — 把文档切分为合适长度的片段（多格式通用，docs/design.md §7 / §16）。

能力：
- split_markdown(text, max_chars): 按 Markdown 标题层级（# / ## / ###）切分，
  保留标题面包屑（breadcrumb）作为上下文前缀，仅用于 .md
- split_text(text, max_chars): 通用切分（txt / pdf / docx / xlsx 等），
  按长度上限 + 段落边界滑动，不带标题面包屑
- 输出纯文本片段列表，供嵌入与检索使用

主要函数：
- split_markdown(text: str, max_chars: int = 800) -> list[str]: 返回片段列表
- split_text(text: str, max_chars: int = 800) -> list[str]: 通用片段列表

关联方案：docs/design.md §7（RAG 管线设计·分块）、§16（多格式与过滤）。
"""


def split_markdown(text: str, max_chars: int = 800) -> list[str]:
    ...


def split_text(text: str, max_chars: int = 800) -> list[str]:
    """通用切分（非 Markdown 文本：txt / pdf / docx / xlsx 解析出的纯文本）。

    按长度上限 + 段落边界滑动切分，不保留标题面包屑（这些格式无 Markdown 标题语义）。
    一期与 split_markdown 共用 max_chars 默认 800 字 / ~200 token。
    """
    ...
