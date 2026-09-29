"""业务·检索 — 语义检索编排（功能需求 FR2）。

能力：
- 将用户查询转为向量（embedder.embed_one）
- 按 (vault_id, embed_profile_id) 定位向量集合（向量空间与模型强绑定，见 §18.2）
- 向量库检索 Top-K 命中，并按阈值过滤低分噪声
- 组装含来源路径 / 标题 / 分数 / 片段内容 / 片段内图片信息（images）的 ChunkHit 列表
- **embedding 与 vault 绑定**：embed_profile_id 由调用方按 vault.embed_profile_id 解析，
  并经 model_service.assert_embed_compatible 守卫（见 §18.2），不可由请求随意指定

主要函数：
- async def retrieve(query, *, top_k, threshold, vault_id, embed_profile_id, embed_runtime)
      -> list[ChunkHit]

关联方案：docs/design.md §5.2（Search 数据流）、§10 模块索引 M04 / M08。
"""
import json

from loguru import logger

from app.core.config import settings
from app.models.schemas import ChunkHit, ModelRuntime
from app.rag.embedder import embed_one
from app.rag.vectorstore import VectorStore
from app.services.model_service import collection_name


async def retrieve(
    query: str,
    *,
    top_k: int = 5,
    threshold: float = 0.0,
    vault_id: int | str | None = None,
    embed_profile_id: int | str | None = None,
    embed_runtime: ModelRuntime | None = None,
) -> list[ChunkHit]:
    """语义检索：query → 向量 → 向量库 Top-K → ChunkHit 列表。

    Args:
        query: 用户查询文本
        top_k: 返回片段数上限
        threshold: 最小相似度（0~1），低于此值的命中被过滤
        vault_id: 目标 vault（决定 collection 隔离命名空间）
        embed_profile_id: 建该 vault 索引时用的 embedding 配置 id（须与 embed_runtime 对应）
        embed_runtime: 检索用 embedding 运行时（须与建索引模型一致）

    Returns:
        ChunkHit 列表，按相似度降序；无 vault 上下文或无命中时返回空列表

    Raises:
        ValueError: 缺少 query / embed_runtime，或 vault_id 与 embed_profile_id 不成对
    """
    if not query or not query.strip():
        raise ValueError("query 不能为空")
    if embed_runtime is None:
        raise ValueError("缺少 embed_runtime，无法做语义检索")
    if (vault_id is None) != (embed_profile_id is None):
        raise ValueError("vault_id 与 embed_profile_id 必须成对提供")

    # 1) 查询转向量
    query_vector = await embed_one(query, embed_runtime)

    # 2) 定位集合并检索
    if vault_id is None:
        # 无 vault 上下文：不应发生（索引都按 vault 分集合），直接返回空
        logger.warning("retrieve 未提供 vault_id，跳过向量库检索")
        return []

    coll = collection_name(vault_id, embed_profile_id)
    store = VectorStore(
        persist_dir=settings.chroma_dir,
        collection_name=coll,
    )

    where = {"vault_id": int(vault_id)}
    raw_hits = await store.query(
        query_vector,
        top_k=top_k,
        threshold=threshold,
        where=where,
    )

    # 3) 组装 ChunkHit（metadata 由 ingest 阶段写入，缺失字段用默认值兜底）
    hits: list[ChunkHit] = []
    for h in raw_hits:
        meta = h.get("metadata") or {}
        hits.append(
            ChunkHit(
                note_id=str(meta.get("note_id", "")),
                file_path=str(meta.get("source_file", meta.get("file_path", ""))),
                title=str(meta.get("title", "")),
                content=h.get("document", ""),
                score=float(h.get("score", 0.0)),
                images=_parse_images(meta.get("images")),
            )
        )

    logger.info(
        "retrieve 完成",
        vault_id=vault_id, collection=coll,
        requested=top_k, returned=len(hits), threshold=threshold,
        model=embed_runtime.model,
    )
    return hits


def _parse_images(raw) -> list[dict]:
    """chunk.metadata["images"] → list[dict]（无图 / 非法值一律按空列表处理）。

    Chroma 只接受基本类型，ingest 阶段已把它 JSON 字符串化。解析失败只丢图片溯源
    信息，绝不能让一条坏 metadata 打断整次检索。
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]
