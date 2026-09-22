"""业务·检索 — 语义检索编排（功能需求 FR2）。

能力：
- 将用户查询转为向量（embedder）
- 向量库检索 Top-K 命中，并按阈值过滤低分噪声
- 组装含来源路径 / 标题 / 分数 / 片段内容的命中列表

主要函数：
- async def retrieve(query: str, top_k: int = 5, threshold: float = 0.0) -> list[ChunkHit]: 返回检索命中

关联方案：docs/design.md §4.2（Search 时序）、§9（Phase 2）。
"""
from app.models.schemas import ChunkHit


async def retrieve(query: str, top_k: int = 5, threshold: float = 0.0) -> list[ChunkHit]:
    ...
