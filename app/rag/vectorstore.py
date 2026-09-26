"""RAG·向量库 — Chroma 本地持久化封装。

能力：
- 向 Chroma collection 写入向量 + 文档 + 元数据（含来源信息）
- 按查询向量检索 Top-K 命中，并按相似度阈值过滤低分噪声
- 按 id 删除向量（增量更新时移除旧 chunk）
- 按 metadata 过滤检索（vault_id / source_file 等）
- 重置集合（更换 embedding 模型时必须先 reset 再重建索引）
- **按 (vault, embedding 模型) 分集合**：不同模型的向量空间不兼容，必须隔离存放（见 §18.2）

主要类：
- class VectorStore:
    - __init__(self, persist_dir: str, collection_name: str = COLLECTION_NAME)
    - async def add(self, ids, vectors, docs, metadatas) -> None: 批量写入（自动分批）
    - async def query(self, vector, top_k, threshold, where) -> list[dict]: 检索并过滤
    - async def delete(self, ids) -> None: 按 id 删除向量
    - async def count(self) -> int: 返回 collection 中向量数
    - async def reset(self) -> None: 清空 collection

关联方案：docs/design.md §6（数据模型·向量库）、§7（RAG 管线设计·检索）、§18.2（embedding 绑定）。
"""
import asyncio
from typing import Any, Sequence

import chromadb
from loguru import logger

COLLECTION_NAME = "notes"
# Chroma 单次 add 上限（HNSW 索引构建内存控制）
_ADD_BATCH_SIZE = 5000


class VectorStore:
    """Chroma 持久化向量库封装。

    Chroma 原生 API 是同步的，这里用 asyncio.to_thread 包装为异步。
    余弦相似度（cosine distance），Chroma 返回的 distance 值越小越相似。
    """

    def __init__(self, persist_dir: str, collection_name: str = COLLECTION_NAME):
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"VectorStore initialized: dir={persist_dir}, collection={collection_name}"
        )

    async def add(
        self,
        ids: Sequence[str],
        vectors: Sequence[Sequence[float]],
        docs: Sequence[str],
        metadatas: Sequence[dict],
    ) -> None:
        """批量写入向量与元数据（自动分批，Chroma 对同 id 的 add 会 upsert）。"""
        total = len(ids)
        if total == 0:
            return

        # 分批写入，避免单次 add 过大导致内存峰值
        for start in range(0, total, _ADD_BATCH_SIZE):
            end = start + _ADD_BATCH_SIZE
            await asyncio.to_thread(
                self._collection.add,
                ids=list(ids[start:end]),
                embeddings=[list(v) for v in vectors[start:end]],
                documents=list(docs[start:end]),
                metadatas=list(metadatas[start:end]),
            )

        logger.debug(f"Added {total} chunks to vectorstore (batch_size={_ADD_BATCH_SIZE})")

    async def query(
        self,
        vector: Sequence[float],
        top_k: int = 5,
        threshold: float = 0.4,
        where: dict | None = None,
    ) -> list[dict]:
        """按查询向量检索 Top-K，按相似度阈值和 metadata 过滤。

        Args:
            vector: 查询向量
            top_k: 返回条数上限
            threshold: 最小相似度（0~1），低于此值的命中被过滤
            where: Chroma metadata 过滤条件，如 {"vault_id": "1"} 或 {"$and": [...]}

        Returns:
            [{"id", "document", "metadata", "score"}] 按相似度降序
        """
        if self._collection.count() == 0:
            return []

        query_kwargs: dict[str, Any] = {
            "query_embeddings": [list(vector)],
            "n_results": top_k,
        }
        if where:
            query_kwargs["where"] = where

        result = await asyncio.to_thread(
            self._collection.query,
            **query_kwargs,
        )

        # Chroma cosine distance: 值越小越相似；distance ∈ [0, 2]
        # 转换为相似度: similarity = 1 - distance
        hits = []
        ids_row = result.get("ids", [[]])[0]
        dists_row = result.get("distances", [[]])[0]
        docs_row = result.get("documents", [[]])[0]
        metas_row = result.get("metadatas", [[]])[0]

        for i in range(len(ids_row)):
            distance = dists_row[i]
            score = max(0.0, 1.0 - distance)
            if score < threshold:
                continue
            hits.append(
                {
                    "id": ids_row[i],
                    "document": docs_row[i],
                    "metadata": metas_row[i],
                    "score": score,
                }
            )

        logger.debug(f"Query returned {len(hits)}/{len(ids_row)} hits (threshold={threshold})")
        return hits

    async def delete(self, ids: Sequence[str]) -> None:
        """按 id 删除向量（增量更新时移除旧 chunk）。"""
        if not ids:
            return
        await asyncio.to_thread(
            self._collection.delete,
            ids=list(ids),
        )
        logger.debug(f"Deleted {len(ids)} chunks from vectorstore")

    async def update_metadata(self, ids: Sequence[str], metadatas: Sequence[dict]) -> None:
        """仅更新指定 id 的 metadata（文件改名零 embedding 用），向量与文档不变。

        Chroma collection.update 只更新显式传入的字段，这里不传 embeddings/documents。
        """
        if not ids:
            return
        await asyncio.to_thread(
            self._collection.update,
            ids=list(ids),
            metadatas=list(metadatas),
        )
        logger.debug(f"Updated metadata for {len(ids)} chunks")

    async def get_all_ids(self) -> list[str]:
        """返回 collection 内全部向量 id（doctor 三向对账用）。"""
        data = await asyncio.to_thread(self._collection.get, include=[])
        return list(data.get("ids", []))

    async def get_metadatas(self, ids: Sequence[str]) -> list[dict]:
        """按 id 批量取 metadata（与 ids 顺序对应，缺失为 None）。"""
        if not ids:
            return []
        data = await asyncio.to_thread(
            self._collection.get,
            ids=list(ids),
            include=["metadatas"],
        )
        return list(data.get("metadatas", []))

    async def count(self) -> int:
        """返回 collection 中向量数。"""
        return await asyncio.to_thread(self._collection.count)

    async def reset(self) -> None:
        """清空 collection（更换 embedding 模型、或该 vault 要重建索引时调用）。"""
        await asyncio.to_thread(
            self._client.delete_collection,
            self._collection_name,
        )
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"VectorStore collection reset: {self._collection_name}")
