"""RAG reranking clients for supported rerank APIs."""
from __future__ import annotations

import math

import httpx

from app.models.schemas import ModelRuntime

_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
_PROTOCOLS = {"siliconflow", "cohere"}


def _endpoint(runtime: ModelRuntime) -> str:
    protocol = runtime.params.get("protocol")
    if protocol not in _PROTOCOLS:
        raise ValueError(f"不支持的 rerank protocol: {protocol!r}")

    base_url = runtime.base_url.strip().rstrip("/")
    if not base_url:
        base_url = (
            "https://api.siliconflow.cn/v1"
            if protocol == "siliconflow"
            else "https://api.cohere.com"
        )

    if base_url.endswith("/rerank"):
        return base_url
    if protocol == "siliconflow":
        suffix = "/rerank" if base_url.endswith("/v1") else "/v1/rerank"
    else:
        suffix = "/rerank" if base_url.endswith("/v2") else "/v2/rerank"
    return f"{base_url}{suffix}"


def _parse_results(payload: object, document_count: int) -> list[tuple[int, float]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("rerank 响应缺少 results 列表")

    results: list[tuple[int, float]] = []
    seen: set[int] = set()
    for item in payload["results"]:
        if not isinstance(item, dict):
            raise ValueError("rerank 响应包含无效结果")
        index = item.get("index")
        score = item.get("relevance_score")
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= document_count
            or index in seen
        ):
            raise ValueError("rerank 响应包含无效或重复的 document index")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or score < 0
            or score > 1
        ):
            raise ValueError("rerank 响应包含无效的 relevance_score")
        seen.add(index)
        results.append((index, float(score)))

    if not results and document_count:
        raise ValueError("rerank 响应 results 不能为空")
    return sorted(results, key=lambda result: result[1], reverse=True)


async def rerank(
    query: str,
    documents: list[str],
    runtime: ModelRuntime,
    *,
    top_n: int | None = None,
) -> list[tuple[int, float]]:
    """Rank candidate documents and return (document index, relevance score)."""
    if runtime.kind != "rerank":
        raise ValueError("rerank 运行时 kind 必须是 rerank")
    if not query.strip():
        raise ValueError("rerank query 不能为空")
    if not documents:
        return []
    if top_n is not None and top_n < 1:
        raise ValueError("top_n 必须大于 0")

    payload: dict[str, object] = {
        "model": runtime.model,
        "query": query,
        "documents": documents,
    }
    if top_n is not None:
        payload["top_n"] = min(top_n, len(documents))

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            _endpoint(runtime),
            headers={
                "Authorization": f"Bearer {runtime.api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return _parse_results(response.json(), len(documents))
