import pytest
from pydantic import SecretStr

from app.models.schemas import ChunkHit, ModelRuntime
from app.services import chat_service
from app.services.retrieval_service import VaultRetrievalScope


@pytest.mark.asyncio
async def test_chat_uses_cross_vault_retrieval_and_identifies_sources(monkeypatch):
    observed = {}
    scopes = [
        VaultRetrievalScope(
            vault_id=3,
            vault_name="Research",
            embed_profile_id=12,
            embed_runtime=ModelRuntime(
                kind="embed",
                name="embed",
                base_url="",
                api_key=SecretStr(""),
                model="embed-model",
            ),
        )
    ]

    async def new_conversation(session, user_id, vault_id):
        assert vault_id is None
        return type("Conversation", (), {"id": 29})()

    async def append_message(*args, **kwargs):
        return None

    async def retrieve_across_vaults(query, **kwargs):
        observed["scopes"] = kwargs["scopes"]
        return [
            ChunkHit(
                note_id="1",
                file_path="same.md",
                title="A note",
                content="Relevant content",
                score=0.82,
                vault_id=3,
                vault_name="Research",
                fusion_score=1 / 61,
            )
        ]

    async def stream_chat(messages, runtime):
        observed["messages"] = messages
        yield "answer"

    monkeypatch.setattr(chat_service.conversation_repo, "new_conversation", new_conversation)
    monkeypatch.setattr(chat_service.conversation_repo, "append_message", append_message)
    monkeypatch.setattr(
        chat_service.retrieval_service,
        "retrieve_across_vaults",
        retrieve_across_vaults,
    )
    monkeypatch.setattr(chat_service.llm_client, "stream_chat", stream_chat)

    events = [
        event
        async for event in chat_service.stream(
            "question",
            session=object(),
            user_id="owner",
            retrieval_scopes=scopes,
            llm_runtime=ModelRuntime(
                kind="llm",
                name="chat",
                base_url="",
                api_key=SecretStr(""),
                model="chat-model",
            ),
        )
    ]

    assert observed["scopes"] == scopes
    sources = next(event["data"] for event in events if event["type"] == "sources")
    assert sources[0]["vault_name"] == "Research"
    assert sources[0]["fusion_score"] == pytest.approx(1 / 61)
    assert "Research · same.md" in observed["messages"][0]["content"]
