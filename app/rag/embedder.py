"""RAG·嵌入 — 文本转向量（OpenAI 兼容 embedding，异步）。

能力：
- 批量将文本片段转为 embedding 向量（分批 + 并发 + 批量失败降级逐条）
- embed_one：单条文本嵌入（供 test_connection 等场景）
- 接入运行时模型配置 ModelRuntime（由 model_service 解析具体用哪个 embedding 模型，见 §18）

所有 AsyncOpenAI 客户端由 app.rag.client.build_client 统一构造，本模块不直接实例化。

主要函数：
- async def embed(texts, runtime, *, batch_size, max_concurrency) -> list[list[float]]
- async def embed_one(text, runtime) -> list[float]

关联方案：docs/design.md §3（技术选型）、§7（RAG 管线设计·嵌入）、§18（多模型管理）。
"""
import asyncio

from loguru import logger

from app.models.schemas import ModelRuntime
from app.rag.client import build_client

# 单次请求最大文本数（OpenAI 限制 2048，国内服务通常更小）
_DEFAULT_BATCH_SIZE = 64
# 最大并发请求数
_DEFAULT_MAX_CONCURRENCY = 4


async def embed_one(text: str, runtime: ModelRuntime) -> list[float]:
    """单条文本嵌入（供连通性测试等轻量场景）。

    Raises:
        ValueError: runtime 缺少必要字段
        RuntimeError: embedding 请求失败
    """
    if not text:
        raise ValueError("text 不能为空")
    if not runtime.base_url or not runtime.model:
        raise ValueError("runtime 缺少 base_url 或 model")

    client = build_client(runtime)
    try:
        kwargs: dict = {"model": runtime.model, "input": text}
        dimensions = runtime.params.get("dim")
        if dimensions:
            kwargs["dimensions"] = dimensions

        resp = await client.embeddings.create(**kwargs)
        return resp.data[0].embedding
    except Exception as e:
        raise RuntimeError(f"embedding 请求失败: {e}") from e
    finally:
        await client.close()


async def embed(
    texts: list[str],
    runtime: ModelRuntime,
    *,
    batch_size: int | None = None,
    max_concurrency: int | None = None,
) -> list[list[float]]:
    """批量将文本转为 embedding 向量。

    Args:
        texts: 待嵌入的文本列表
        runtime: 运行时模型配置（base_url / api_key / model）
        batch_size: 单次请求最大文本数，默认 64
        max_concurrency: 最大并发请求数，默认 4

    Returns:
        向量列表，顺序与 texts 一一对应

    Raises:
        ValueError: texts 为空或 runtime 缺少必要字段
        RuntimeError: embedding 请求失败
    """
    if not texts:
        return []
    if not runtime.base_url or not runtime.model:
        raise ValueError("runtime 缺少 base_url 或 model")

    bs = batch_size or runtime.params.get("batch_size", _DEFAULT_BATCH_SIZE)
    mc = max_concurrency or runtime.params.get("max_concurrency", _DEFAULT_MAX_CONCURRENCY)

    client = build_client(runtime)
    model = runtime.model
    dimensions = runtime.params.get("dim")  # 部分模型支持指定维度

    # 分批
    batches = [texts[i : i + bs] for i in range(0, len(texts), bs)]
    semaphore = asyncio.Semaphore(mc)

    async def _embed_single(text: str) -> list[float]:
        """单条文本嵌入（降级路径）。"""
        kwargs: dict = {"model": model, "input": text}
        if dimensions:
            kwargs["dimensions"] = dimensions
        resp = await client.embeddings.create(**kwargs)
        return resp.data[0].embedding

    async def _embed_batch(batch: list[str], batch_idx: int) -> list[list[float]]:
        async with semaphore:
            try:
                kwargs: dict = {"model": model, "input": batch}
                if dimensions:
                    kwargs["dimensions"] = dimensions
                resp = await client.embeddings.create(**kwargs)
                sorted_data = sorted(resp.data, key=lambda x: x.index)
                return [d.embedding for d in sorted_data]
            except Exception as e:
                # 批量请求失败时，若 batch 大于 1，降级为逐条请求
                if len(batch) > 1:
                    logger.warning(
                        "批量 embedding 失败，降级为逐条请求",
                        batch=batch_idx, batch_size=len(batch),
                        model=model, error=str(e),
                    )
                    return await asyncio.gather(
                        *[_embed_single(t) for t in batch]
                    )
                logger.error(
                    "embedding 请求失败",
                    batch=batch_idx, batch_size=len(batch), model=model, error=str(e),
                )
                raise RuntimeError(f"embedding 请求失败 (batch {batch_idx}): {e}") from e

    # 并发请求所有批次
    try:
        results = await asyncio.gather(
            *[_embed_batch(b, i) for i, b in enumerate(batches)]
        )
    finally:
        await client.close()

    # 展平
    vectors: list[list[float]] = []
    for batch_vectors in results:
        vectors.extend(batch_vectors)

    logger.info(
        "embedding 完成",
        total_texts=len(texts), batches=len(batches),
        model=model, dim=len(vectors[0]) if vectors else 0,
    )
    return vectors
