"""RAG·向量库 — Chroma 本地持久化封装。

能力：
- 向 Chroma collection 写入向量 + 文档 + 元数据（含来源信息）
- 按查询向量检索 Top-K 命中，并按阈值过滤低分噪声
- 重置集合（更换 embedding 模型时必须先 reset 再重建索引）
- **按 (vault, embedding 模型) 分集合**：不同模型的向量空间不兼容，必须隔离存放（见 §18.2）

主要类：
- class VectorStore:
    - __init__(self, persist_dir: str, collection_name: str = COLLECTION_NAME): 加载 / 创建持久化客户端与 collection
          collection_name 由 model_service.collection_name(vault_id, profile_id) 生成
    - async def add(self, ids, vectors, docs, metadatas) -> None: 批量写入
    - async def query(self, vector, top_k, threshold) -> list[dict]: 检索并过滤
    - async def reset(self) -> None: 清空 collection

关联方案：docs/design.md §6（数据模型·向量库）、§7（RAG 管线设计·检索）、§18.2（embedding 绑定）。
"""
import asyncio
from typing import Sequence

import chromadb
from loguru import logger

COLLECTION_NAME = "notes"


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
        """批量写入向量与元数据。

        Chroma 对同 id 的 add 会 upsert，因此重复摄取时自动覆盖旧数据。
        """
        await asyncio.to_thread(
            self._collection.add,
            ids=list(ids),
            embeddings=[list(v) for v in vectors],
            documents=list(docs),
            metadatas=list(metadatas),
        )
        logger.debug(f"Added {len(ids)} chunks to vectorstore")

    async def query(
        self,
        vector: Sequence[float],
        top_k: int = 5,
        threshold: float = 0.4,
    ) -> list[dict]:
        """按查询向量检索 Top-K，按相似度阈值过滤。

        Args:
            vector: 查询向量
            top_k: 返回条数上限
            threshold: 最小相似度（0~1），低于此值的命中被过滤

        Returns:
            [{"id", "document", "metadata", "score"}] 按相似度降序
        """
        if self._collection.count() == 0:
            return []

        result = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=[list(vector)],
            n_results=top_k,
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
