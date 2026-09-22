"""业务·检索 — 语义检索编排（功能需求 FR2）。

能力：
- 将用户查询转为向量（embedder）
- 向量库检索 Top-K 命中，并按阈值过滤低分噪声
- 组装含来源路径 / 标题 / 分数 / 片段内容的命中列表
- **embedding 与 vault 绑定**：embed_runtime 由调用方按 vault.embed_profile_id 解析，
  并经 model_service.assert_embed_compatible 守卫（见 §18.2），不可由请求随意指定

主要函数：
- async def retrieve(query, top_k=5, threshold=0.0, vault_id=None, embed_runtime=None) -> list[ChunkHit]: 返回检索命中

关联方案：docs/design.md §4.2（Search 时序）、§9（Phase 2）、§18（多模型管理）。
"""
from app.models.schemas import ChunkHit, ModelRuntime


async def retrieve(query: str, top_k: int = 5, threshold: float = 0.0,
                   vault_id: str | None = None,
                   embed_runtime: "ModelRuntime | None" = None) -> list[ChunkHit]:
    ...
