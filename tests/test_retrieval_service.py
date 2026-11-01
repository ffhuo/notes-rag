import pytest
from pydantic import SecretStr

from app.models.schemas import ModelRuntime
from app.services import retrieval_service


@pytest.mark.asyncio
async def test_retrieve_reranks_candidate_pool_and_preserves_vector_score(monkeypatch):
    observed = {}

    async def fake_embed_one(query, runtime):
        return [0.1, 0.2]

    class FakeVectorStore:
        def __init__(self, **kwargs):
            pass

        async def query(self, vector, top_k, threshold, where):
            observed["candidate_k"] = top_k
            observed["threshold"] = threshold
            return [
                {
                    "id": "chunk-1",
                    "document": "first candidate",
                    "metadata": {
                        "note_id": "1",
                        "source_file": "a.md",
                        "title": "First note",
                    },
                    "score": 0.9,
                },
                {
                    "id": "chunk-2",
                    "document": "second candidate",
                    "metadata": {"note_id": "2", "source_file": "b.md"},
                    "score": 0.8,
                },
                {
                    "id": "chunk-3",
                    "document": "third candidate",
                    "metadata": {"note_id": "3", "source_file": "c.md"},
                    "score": 0.7,
                },
            ]

    async def fake_rerank(query, documents, runtime, *, top_n):
        observed["documents"] = documents
        observed["top_n"] = top_n
        return [(2, 0.99), (0, 0.73)]

    monkeypatch.setattr(retrieval_service, "embed_one", fake_embed_one)
    monkeypatch.setattr(retrieval_service, "VectorStore", FakeVectorStore)
    monkeypatch.setattr(retrieval_service, "rerank_documents", fake_rerank)

    hits = await retrieval_service.retrieve(
        "question",
        top_k=2,
        threshold=0.25,
        vault_id=1,
        embed_profile_id=7,
        embed_runtime=ModelRuntime(
            kind="embed",
            name="embed",
            base_url="",
            api_key=SecretStr(""),
            model="embed-model",
        ),
        rerank_runtime=ModelRuntime(
            kind="rerank",
            name="rerank",
            base_url="",
            api_key=SecretStr(""),
            model="rerank-model",
            params={"protocol": "cohere"},
        ),
    )

    assert observed == {
        "candidate_k": 20,
        "threshold": 0.25,
        "documents": [
            "Title: First note\n\nfirst candidate",
            "second candidate",
            "third candidate",
        ],
        "top_n": 2,
    }
    assert [hit.note_id for hit in hits] == ["3", "1"]
    assert [hit.score for hit in hits] == [0.7, 0.9]
    assert [hit.rerank_score for hit in hits] == [0.99, 0.73]


@pytest.mark.asyncio
async def test_retrieve_without_reranker_keeps_vector_top_k(monkeypatch):
    observed = {}

    async def fake_embed_one(query, runtime):
        return [0.1, 0.2]

    class FakeVectorStore:
        def __init__(self, **kwargs):
            pass

        async def query(self, vector, top_k, threshold, where):
            observed["top_k"] = top_k
            return [
                {"document": str(index), "metadata": {"note_id": str(index)}, "score": 1.0}
                for index in range(3)
            ]

    async def unexpected_rerank(*args, **kwargs):
        raise AssertionError("reranker must not run when not configured")

    monkeypatch.setattr(retrieval_service, "embed_one", fake_embed_one)
    monkeypatch.setattr(retrieval_service, "VectorStore", FakeVectorStore)
    monkeypatch.setattr(retrieval_service, "rerank_documents", unexpected_rerank)

    hits = await retrieval_service.retrieve(
        "question",
        top_k=2,
        vault_id=1,
        embed_profile_id=7,
        embed_runtime=ModelRuntime(
            kind="embed",
            name="embed",
            base_url="",
            api_key=SecretStr(""),
            model="embed-model",
        ),
    )

    assert observed["top_k"] == 2
    assert [hit.note_id for hit in hits] == ["0", "1"]
    assert all(hit.rerank_score is None for hit in hits)


@pytest.mark.asyncio
async def test_retrieve_falls_back_to_vector_order_when_reranking_fails(monkeypatch):
    warnings = []

    async def fake_embed_one(query, runtime):
        return [0.1, 0.2]

    class FakeVectorStore:
        def __init__(self, **kwargs):
            pass

        async def query(self, vector, top_k, threshold, where):
            return [
                {
                    "document": f"candidate {index}",
                    "metadata": {"note_id": str(index)},
                    "score": 1.0 - index / 10,
                }
                for index in range(3)
            ]

    async def failing_rerank(*args, **kwargs):
        raise TimeoutError("rerank API timed out")

    monkeypatch.setattr(retrieval_service, "embed_one", fake_embed_one)
    monkeypatch.setattr(retrieval_service, "VectorStore", FakeVectorStore)
    monkeypatch.setattr(retrieval_service, "rerank_documents", failing_rerank)
    monkeypatch.setattr(
        retrieval_service.logger,
        "warning",
        lambda message, **context: warnings.append((message, context)),
    )

    hits = await retrieval_service.retrieve(
        "question",
        top_k=2,
        vault_id=1,
        embed_profile_id=7,
        embed_runtime=ModelRuntime(
            kind="embed",
            name="embed",
            base_url="",
            api_key=SecretStr(""),
            model="embed-model",
        ),
        rerank_runtime=ModelRuntime(
            kind="rerank",
            name="rerank",
            base_url="",
            api_key=SecretStr(""),
            model="rerank-model",
            params={"protocol": "cohere"},
        ),
    )

    assert [hit.note_id for hit in hits] == ["0", "1"]
    assert all(hit.rerank_score is None for hit in hits)
    assert warnings[0][0] == "rerank 失败，降级为向量排序"


@pytest.mark.asyncio
async def test_retrieve_across_vaults_fuses_ranks_without_comparing_scores(monkeypatch):
    from app.services.retrieval_service import VaultRetrievalScope

    scope1 = VaultRetrievalScope(
        vault_id=1,
        vault_name="Personal",
        embed_profile_id=7,
        embed_runtime=ModelRuntime(
            kind="embed",
            name="embed-a",
            base_url="",
            api_key=SecretStr(""),
            model="embed-model-a",
        ),
    )
    scope2 = VaultRetrievalScope(
        vault_id=2,
        vault_name="Work",
        embed_profile_id=8,
        embed_runtime=ModelRuntime(
            kind="embed",
            name="embed-b",
            base_url="",
            api_key=SecretStr(""),
            model="embed-model-b",
        ),
    )

    async def fake_retrieve(query, **kwargs):
        if kwargs["vault_id"] == 1:
            return [
                retrieval_service.ChunkHit(
                    note_id="personal-first",
                    file_path="same.md",
                    title="Personal first",
                    content="first",
                    score=0.1,
                ),
                retrieval_service.ChunkHit(
                    note_id="personal-second",
                    file_path="same.md",
                    title="Personal second",
                    content="second",
                    score=0.99,
                ),
            ]
        return [
            retrieval_service.ChunkHit(
                note_id="work-first",
                file_path="same.md",
                title="Work first",
                content="first",
                score=0.8,
            ),
        ]

    monkeypatch.setattr(retrieval_service, "retrieve", fake_retrieve)

    hits = await retrieval_service.retrieve_across_vaults(
        "question",
        scopes=[scope1, scope2],
        top_k=2,
    )

    assert [(hit.vault_id, hit.vault_name, hit.note_id) for hit in hits] == [
        (1, "Personal", "personal-first"),
        (2, "Work", "work-first"),
    ]
    assert hits[0].fusion_score == pytest.approx(1 / 61)
    assert hits[1].fusion_score == pytest.approx(1 / 61)
