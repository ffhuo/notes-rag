"""RAG·分块 — 把 Markdown 笔记切分为合适长度的片段。

能力：
- 按 Markdown 标题层级（# / ## / ###）切分
- 按长度上限滑动切分，保留标题面包屑（breadcrumb）作为上下文前缀
- 输出纯文本片段列表，供嵌入与检索使用

主要函数：
- split_markdown(text: str, max_chars: int = 800) -> list[str]: 返回片段列表

关联方案：docs/design.md §7（RAG 管线设计·分块）。
"""


def split_markdown(text: str, max_chars: int = 800) -> list[str]:
    ...
