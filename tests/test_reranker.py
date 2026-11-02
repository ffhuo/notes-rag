import json

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.api.routes.models import _validate_rerank_protocol
from app.models.schemas import ModelRuntime
from app.rag.reranker import rerank
from app.repositories import model_repo
from app.services import model_service


@pytest.mark.asyncio
async def test_siliconflow_rerank_sends_candidates_and_returns_ranked_indexes(monkeypatch):
    observed = {}
    async_client = httpx.AsyncClient

    def handle(request):
        observed["url"] = str(request.url)
        observed["authorization"] = request.headers.get("Authorization")
        observed["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.93},
                    {"index": 0, "relevance_score": 0.42},
                ]
            },
        )

    monkeypatch.setattr(
        "app.rag.reranker.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    runtime = ModelRuntime(
        kind="rerank",
        name="siliconflow-reranker",
        base_url="https://api.siliconflow.cn/v1",
        api_key=SecretStr("test-key"),
        model="BAAI/bge-reranker-v2-m3",
        params={"protocol": "siliconflow"},
    )

    results = await rerank("query", ["first", "second"], runtime, top_n=2)

    assert observed["url"] == "https://api.siliconflow.cn/v1/rerank"
    assert observed["authorization"] == "Bearer test-key"
    assert json.loads(observed["body"]) == {
        "model": "BAAI/bge-reranker-v2-m3",
        "query": "query",
        "documents": ["first", "second"],
        "top_n": 2,
    }
    assert results == [(1, 0.93), (0, 0.42)]


@pytest.mark.asyncio
async def test_cohere_rerank_uses_v2_endpoint_and_rejects_duplicate_indexes(monkeypatch):
    observed = {}
    async_client = httpx.AsyncClient

    def handle(request):
        observed["url"] = str(request.url)
        observed["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.8},
                    {"index": 0, "relevance_score": 0.7},
                ]
            },
        )

    monkeypatch.setattr(
        "app.rag.reranker.httpx.AsyncClient",
        lambda **kwargs: async_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    runtime = ModelRuntime(
        kind="rerank",
        name="cohere-reranker",
        base_url="",
        api_key=SecretStr("test-key"),
        model="rerank-v4.0-fast",
        params={"protocol": "cohere"},
    )

    with pytest.raises(ValueError, match="重复"):
        await rerank("query", ["first", "second"], runtime, top_n=1)

    assert observed["url"] == "https://api.cohere.com/v2/rerank"
    assert json.loads(observed["body"])["top_n"] == 1


@pytest.mark.asyncio
async def test_resolve_rerank_runtime_uses_only_enabled_default(monkeypatch):
    profile = model_service.ModelProfile(
        user_id="user-1",
        kind="rerank",
        name="cohere",
        base_url="",
        api_key="secret",
        model="rerank-v4.0-fast",
        params_json='{"protocol":"cohere"}',
        is_default=True,
        enabled=True,
    )

    async def find_default(session, user_id, kind):
        assert (user_id, kind) == ("user-1", "rerank")
        return profile

    monkeypatch.setattr(model_repo, "get_default", find_default)

    runtime = await model_service.resolve_rerank_runtime(None, "user-1")

    assert runtime.kind == "rerank"
    assert runtime.model == "rerank-v4.0-fast"
    assert runtime.params == {"protocol": "cohere"}

    profile.enabled = False
    assert await model_service.resolve_rerank_runtime(None, "user-1") is None

    profile.enabled = True
    async def no_default(session, user_id, kind):
        return None

    monkeypatch.setattr(model_repo, "get_default", no_default)
    assert await model_service.resolve_rerank_runtime(None, "user-1") is None


@pytest.mark.asyncio
async def test_rerank_profile_connection_test_calls_reranker(monkeypatch):
    called = {}

    async def fake_rerank(query, documents, runtime, *, top_n):
        called.update(query=query, documents=documents, model=runtime.model, top_n=top_n)
        return [(0, 0.9)]

    monkeypatch.setattr(model_service, "rerank", fake_rerank)
    runtime = ModelRuntime(
        kind="rerank",
        name="cohere",
        base_url="",
        api_key=SecretStr("key"),
        model="rerank-v4.0-fast",
        params={"protocol": "cohere"},
    )

    result = await model_service.test_connection(runtime)

    assert result.ok is True
    assert called["model"] == "rerank-v4.0-fast"
    assert called["top_n"] == 1


@pytest.mark.asyncio
async def test_rerank_connection_test_reports_provider_errors(monkeypatch):
    async def failing_rerank(*args, **kwargs):
        raise httpx.HTTPStatusError(
            "provider unavailable",
            request=httpx.Request("POST", "https://api.cohere.com/v2/rerank"),
            response=httpx.Response(503),
        )

    monkeypatch.setattr(model_service, "rerank", failing_rerank)
    runtime = ModelRuntime(
        kind="rerank",
        name="cohere",
        base_url="",
        api_key=SecretStr("key"),
        model="rerank-v4.0-fast",
        params={"protocol": "cohere"},
    )

    result = await model_service.test_connection(runtime)

    assert result.ok is False
    assert result.error


def test_rerank_model_requires_supported_protocol():
    _validate_rerank_protocol("rerank", {"protocol": "siliconflow"})
    _validate_rerank_protocol("rerank", {"protocol": "cohere"})

    with pytest.raises(HTTPException) as error:
        _validate_rerank_protocol("rerank", {})

    assert error.value.status_code == 422
