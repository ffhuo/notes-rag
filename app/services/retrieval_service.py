"""业务·检索 — 语义检索编排（功能需求 FR2）。

能力：
- 将用户查询转为向量（embedder.embed_one）
- 按 (vault_id, embed_profile_id) 定位向量集合（向量空间与模型强绑定，见 §18.2）
- 向量库召回候选并按阈值过滤低分噪声；配置默认 reranker 时执行精排
- 组装含来源路径 / 标题 / 分数 / 片段内容 / 片段内图片信息（images）的 ChunkHit 列表
- **embedding 与 vault 绑定**：embed_profile_id 由调用方按 vault.embed_profile_id 解析，
  并经 model_service.assert_embed_compatible 守卫（见 §18.2），不可由请求随意指定

主要函数：
- async def retrieve(query, *, top_k, threshold, vault_id, embed_profile_id, embed_runtime, rerank_runtime)
      -> list[ChunkHit]
- async def retrieve_across_vaults(query, *, scopes, top_k, rerank_runtime)
      -> list[ChunkHit]（按 RRF 融合各 vault 的名次）

关联方案：docs/design.md §5.2（Search 数据流）、§10 模块索引 M04 / M08。
"""
import json
import time
from dataclasses import dataclass

from loguru import logger

from app.core.config import settings
from app.models.schemas import ChunkHit, ModelRuntime
from app.rag.embedder import embed_one
from app.rag.reranker import rerank as rerank_documents
from app.rag.vectorstore import VectorStore
from app.services.model_service import collection_name

_RRF_K = 60


@dataclass(frozen=True)
class VaultRetrievalScope:
    """A vault and the embedding profile that owns its indexed vector space."""

    vault_id: int
    vault_name: str
    embed_profile_id: int | str
    embed_runtime: ModelRuntime


async def retrieve(
    query: str,
    *,
    top_k: int = 5,
    threshold: float = 0.0,
    vault_id: int | str | None = None,
    embed_profile_id: int | str | None = None,
    embed_runtime: ModelRuntime | None = None,
    rerank_runtime: ModelRuntime | None = None,
) -> list[ChunkHit]:
    """语义检索：query → 向量 → 向量库 Top-K → ChunkHit 列表。

    Args:
        query: 用户查询文本
        top_k: 返回片段数上限
        threshold: 最小相似度（0~1），低于此值的命中被过滤
        vault_id: 目标 vault（决定 collection 隔离命名空间）
        embed_profile_id: 建该 vault 索引时用的 embedding 配置 id（须与 embed_runtime 对应）
        embed_runtime: 检索用 embedding 运行时（须与建索引模型一致）
        rerank_runtime: 可选精排运行时；传入时过召回后重排并返回最终 top_k

    Returns:
        ChunkHit 列表；未配置精排时按向量相似度排序，精排故障时回退该排序

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
    rerank_enabled = rerank_runtime is not None and top_k > 0
    candidate_k = min(max(top_k * 4, 20), 100) if rerank_enabled else top_k
    raw_hits = await store.query(
        query_vector,
        top_k=candidate_k,
        threshold=threshold,
        where=where,
    )

    rerank_scores: list[float] = []
    rerank_candidate_count = 0
    rerank_elapsed_ms: int | None = None
    if rerank_enabled and raw_hits:
        rerank_candidate_count = len(raw_hits)
        started = time.monotonic()
        try:
            ranked = await rerank_documents(
                query,
                [
                    (
                        f"Title: {hit['metadata'].get('title')}\n\n"
                        if (hit.get("metadata") or {}).get("title")
                        else ""
                    )
                    + str(hit.get("document") or "")
                    for hit in raw_hits
                ],
                rerank_runtime,
                top_n=min(top_k, len(raw_hits)),
            )
            if not ranked:
                raise ValueError("reranker returned no ranked candidates")

            reranked_hits = []
            seen: set[int] = set()
            for index, score in ranked:
                if (
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or index < 0
                    or index >= len(raw_hits)
                    or index in seen
                ):
                    raise ValueError("reranker returned an invalid candidate index")
                seen.add(index)
                reranked_hits.append(raw_hits[index])
                rerank_scores.append(score)
            raw_hits = reranked_hits[:top_k]
            rerank_scores = rerank_scores[:top_k]
        except Exception as e:
            rerank_elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "rerank 失败，降级为向量排序",
                vault_id=vault_id,
                profile=rerank_runtime.name,
                model=rerank_runtime.model,
                protocol=rerank_runtime.params.get("protocol"),
                candidates=len(raw_hits),
                elapsed_ms=rerank_elapsed_ms,
                error=str(e),
            )
            rerank_scores = []
            raw_hits = raw_hits[:top_k]
        else:
            rerank_elapsed_ms = int((time.monotonic() - started) * 1000)
    elif not rerank_enabled:
        raw_hits = raw_hits[:top_k]

    # 3) 组装 ChunkHit（metadata 由 ingest 阶段写入，缺失字段用默认值兜底）
    hits: list[ChunkHit] = []
    for i, h in enumerate(raw_hits):
        meta = h.get("metadata") or {}
        hits.append(
            ChunkHit(
                note_id=str(meta.get("note_id", "")),
                file_path=str(meta.get("source_file", meta.get("file_path", ""))),
                title=str(meta.get("title", "")),
                content=h.get("document", ""),
                score=float(h.get("score", 0.0)),
                images=_parse_images(meta.get("images")),
                rerank_score=rerank_scores[i] if rerank_scores else None,
            )
        )

    logger.info(
        "retrieve 完成",
        vault_id=vault_id, collection=coll,
        requested=top_k, returned=len(hits), threshold=threshold,
        model=embed_runtime.model,
        reranker=rerank_runtime.model if rerank_runtime is not None else None,
        rerank_protocol=(
            rerank_runtime.params.get("protocol")
            if rerank_runtime is not None
            else None
        ),
        rerank_candidates=rerank_candidate_count,
        rerank_elapsed_ms=rerank_elapsed_ms,
    )
    return hits


async def retrieve_across_vaults(
    query: str,
    *,
    scopes: list[VaultRetrievalScope],
    top_k: int = 5,
    threshold: float = 0.0,
    rerank_runtime: ModelRuntime | None = None,
) -> list[ChunkHit]:
    """Retrieve within each vault's embedding space, then fuse the ranked lists.

    Vector and reranker scores are only meaningful within a vault's retrieval
    context. Reciprocal rank fusion combines those lists without comparing the
    underlying score scales.
    """
    ranked_hits: list[tuple[float, ChunkHit]] = []
    for scope in scopes:
        vault_hits = await retrieve(
            query,
            top_k=top_k,
            threshold=threshold,
            vault_id=scope.vault_id,
            embed_profile_id=scope.embed_profile_id,
            embed_runtime=scope.embed_runtime,
            rerank_runtime=rerank_runtime,
        )
        for rank, hit in enumerate(vault_hits, start=1):
            fusion_score = 1 / (_RRF_K + rank)
            ranked_hits.append(
                (
                    fusion_score,
                    hit.model_copy(
                        update={
                            "vault_id": scope.vault_id,
                            "vault_name": scope.vault_name,
                            "fusion_score": fusion_score,
                        }
                    ),
                )
            )

    ranked_hits.sort(key=lambda result: result[0], reverse=True)
    return [hit for _, hit in ranked_hits[:top_k]]


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
