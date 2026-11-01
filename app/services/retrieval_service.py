"""业务·检索 — 语义检索编排（功能需求 FR2）。

能力：
- 将用户查询转为向量（embedder.embed_one）
- 按 (vault_id, embed_profile_id) 定位向量集合（向量空间与模型强绑定，见 §18.2）
- 并行执行向量召回与 SQLite FTS5 BM25 召回，按 RRF 融合；可选 reranker 对融合候选精排
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
import asyncio
import json
import time
from dataclasses import dataclass

from loguru import logger

from app.core.config import settings
from app.core.database import session_scope
from app.models.schemas import ChunkHit, ModelRuntime
from app.rag.embedder import embed_one
from app.rag.reranker import rerank as rerank_documents
from app.rag.vectorstore import VectorStore
from app.repositories import bm25_repo
from app.services.model_service import collection_name


@dataclass(frozen=True)
class VaultRetrievalScope:
    """A vault and the embedding profile that owns its indexed vector space."""

    vault_id: int
    vault_name: str
    embed_profile_id: int | str
    embed_runtime: ModelRuntime


@dataclass
class _RankedCandidate:
    key: str
    hit: ChunkHit
    fusion_score: float = 0.0


def _candidate_count(top_k: int, multiplier: int, minimum: int, maximum: int) -> int:
    return min(max(top_k * multiplier, minimum), maximum)


async def _search_bm25(
    query: str, vault_id: int, limit: int
) -> list[bm25_repo.Bm25Hit]:
    started = time.monotonic()
    try:
        async with session_scope() as session:
            return await bm25_repo.search(session, query, vault_id, limit)
    except Exception as e:
        logger.warning(
            "BM25 检索失败，降级为向量召回",
            vault_id=vault_id,
            candidates=limit,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            error=str(e),
        )
        return []


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
        ChunkHit 列表；精排故障时记录告警并回退到召回融合顺序

    Raises:
        ValueError: 缺少 query / embed_runtime，或 vault_id 与 embed_profile_id 不成对
    """
    if not query or not query.strip():
        raise ValueError("query 不能为空")
    if embed_runtime is None:
        raise ValueError("缺少 embed_runtime，无法做语义检索")
    if (vault_id is None) != (embed_profile_id is None):
        raise ValueError("vault_id 与 embed_profile_id 必须成对提供")
    if top_k <= 0:
        return []

    query_vector = await embed_one(query, embed_runtime)

    if vault_id is None:
        logger.warning("retrieve 未提供 vault_id，跳过向量库检索")
        return []

    coll = collection_name(vault_id, embed_profile_id)
    store = VectorStore(
        persist_dir=settings.chroma_dir,
        collection_name=coll,
    )

    where = {"vault_id": int(vault_id)}
    candidate_k = (
        _candidate_count(
            top_k,
            settings.vector_recall_multiplier,
            settings.vector_recall_min,
            settings.vector_recall_max,
        )
        if settings.bm25_enabled or rerank_runtime is not None
        else top_k
    )
    vector_query = store.query(
        query_vector,
        top_k=candidate_k,
        threshold=threshold,
        where=where,
    )
    if settings.bm25_enabled:
        bm25_limit = _candidate_count(
            top_k,
            settings.bm25_recall_multiplier,
            settings.bm25_recall_min,
            settings.bm25_recall_max,
        )
        raw_hits, bm25_hits = await asyncio.gather(
            vector_query,
            _search_bm25(query, int(vault_id), bm25_limit),
        )
    else:
        raw_hits = await vector_query
        bm25_hits = []

    vector_candidates: list[_RankedCandidate] = []
    for raw_hit in raw_hits:
        metadata = raw_hit.get("metadata") or {}
        vector_candidates.append(
            _RankedCandidate(
                key=str(raw_hit.get("id") or (
                    f"{metadata.get('note_id', '')}:{raw_hit.get('document', '')}"
                )),
                hit=ChunkHit(
                    note_id=str(metadata.get("note_id", "")),
                    file_path=str(metadata.get("source_file", metadata.get("file_path", ""))),
                    title=str(metadata.get("title", "")),
                    content=raw_hit.get("document", ""),
                    score=float(raw_hit.get("score", 0.0)),
                    vault_id=int(vault_id),
                    images=_parse_images(metadata.get("images")),
                ),
            )
        )

    bm25_candidates: list[_RankedCandidate] = []
    if settings.bm25_enabled:
        bm25_candidates = [
            _RankedCandidate(
                key=hit.vector_id,
                hit=ChunkHit(
                    note_id=hit.note_id,
                    file_path=hit.file_path,
                    title=hit.title,
                    content=hit.content,
                    score=0.0,
                    bm25_score=hit.score,
                    vault_id=int(vault_id),
                    vector_recalled=False,
                ),
            )
            for hit in bm25_hits
        ]
    fused_by_key = {candidate.key: candidate for candidate in vector_candidates}
    if settings.bm25_enabled:
        for rank, candidate in enumerate(vector_candidates, start=1):
            candidate.fusion_score += 1 / (settings.retrieval_rrf_k + rank)
        for rank, candidate in enumerate(bm25_candidates, start=1):
            existing = fused_by_key.get(candidate.key)
            if existing is None:
                existing = candidate
                fused_by_key[candidate.key] = existing
            else:
                existing.hit = existing.hit.model_copy(
                    update={"bm25_score": candidate.hit.bm25_score}
                )
            existing.fusion_score += 1 / (settings.retrieval_rrf_k + rank)

    ranked_candidates = list(fused_by_key.values())
    if settings.bm25_enabled:
        ranked_candidates.sort(key=lambda candidate: candidate.fusion_score, reverse=True)
        for candidate in ranked_candidates:
            candidate.hit = candidate.hit.model_copy(
                update={"fusion_score": candidate.fusion_score}
            )

    if rerank_runtime is not None and ranked_candidates:
        rerank_limit = _candidate_count(
            top_k,
            settings.rerank_candidate_multiplier,
            settings.rerank_candidate_min,
            settings.rerank_candidate_max,
        )
        rerank_candidates = ranked_candidates[:rerank_limit]
        started = time.monotonic()
        try:
            ranked = await rerank_documents(
                query,
                [
                    (f"Title: {candidate.hit.title}\n\n" if candidate.hit.title else "")
                    + candidate.hit.content
                    for candidate in rerank_candidates
                ],
                rerank_runtime,
                top_n=min(top_k, len(rerank_candidates)),
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
                    or index >= len(rerank_candidates)
                    or index in seen
                ):
                    raise ValueError("reranker returned an invalid candidate index")
                seen.add(index)
                reranked_hits.append(
                    rerank_candidates[index].hit.model_copy(
                        update={"rerank_score": score}
                    )
                )
            hits = reranked_hits[:top_k]
        except Exception as e:
            logger.warning(
                "rerank 失败，降级为混合召回排序",
                vault_id=vault_id,
                profile=rerank_runtime.name,
                model=rerank_runtime.model,
                protocol=rerank_runtime.params.get("protocol"),
                candidates=len(rerank_candidates),
                elapsed_ms=int((time.monotonic() - started) * 1000),
                error=str(e),
            )
            hits = [candidate.hit for candidate in ranked_candidates[:top_k]]
    else:
        hits = [candidate.hit for candidate in ranked_candidates[:top_k]]

    logger.info(
        "retrieve 完成",
        vault_id=vault_id, collection=coll,
        requested=top_k, returned=len(hits), threshold=threshold,
        model=embed_runtime.model,
        bm25_enabled=settings.bm25_enabled,
        vector_candidates=len(vector_candidates),
        bm25_candidates=len(bm25_candidates),
        reranker=rerank_runtime.model if rerank_runtime is not None else None,
        rerank_protocol=(
            rerank_runtime.params.get("protocol")
            if rerank_runtime is not None
            else None
        ),
        rerank_candidates=(
            len(rerank_candidates)
            if rerank_runtime is not None and ranked_candidates
            else 0
        ),
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
            fusion_score = 1 / (settings.retrieval_rrf_k + rank)
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
