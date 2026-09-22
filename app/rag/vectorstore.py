"""RAG·向量库 — Chroma 本地持久化封装。

能力：
- 向 Chroma collection 写入向量 + 文档 + 元数据（含来源信息）
- 按查询向量检索 Top-K 命中，并按阈值过滤低分噪声
- 重置集合（更换 embedding 模型时必须先 reset 再重建索引）

主要类：
- class VectorStore:
    - __init__(self, persist_dir: str): 加载 / 创建持久化客户端与 collection
    - async def add(self, ids, vectors, docs, metadatas) -> None: 批量写入
    - async def query(self, vector, top_k, threshold) -> list[dict]: 检索并过滤
    - async def reset(self) -> None: 清空 collection

关联方案：docs/design.md §6（数据模型·向量库）、§7（RAG 管线设计·检索）。
"""
import chromadb


class VectorStore:
    def __init__(self, persist_dir: str):
        ...

    async def add(self, ids, vectors, docs, metadatas) -> None:
        ...

    async def query(self, vector, top_k: int, threshold: float) -> list[dict]:
        ...

    async def reset(self) -> None:
        ...
