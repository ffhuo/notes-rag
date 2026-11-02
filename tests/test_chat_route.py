from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.api.routes import chat as chat_route
from app.models.schemas import ModelRuntime


@pytest.mark.asyncio
async def test_all_chat_scopes_use_each_vaults_index_profile(monkeypatch):
    vaults = [
        SimpleNamespace(
            id=1,
            name="Personal",
            indexed_at=object(),
            embed_profile_id=7,
        ),
        SimpleNamespace(
            id=2,
            name="Work",
            indexed_at=object(),
            embed_profile_id=8,
        ),
        SimpleNamespace(
            id=3,
            name="Unindexed",
            indexed_at=None,
            embed_profile_id=None,
        ),
    ]

    async def list_vaults(session, user_id):
        assert user_id == "owner"
        return vaults

    async def resolve_embed(session, user_id, vault):
        profile_id = vault.embed_profile_id
        return (
            ModelRuntime(
                kind="embed",
                name=f"embed-{profile_id}",
                base_url="",
                api_key=SecretStr(""),
                model=f"embed-model-{profile_id}",
            ),
            profile_id,
        )

    monkeypatch.setattr(chat_route.vault_repo, "list_vaults", list_vaults)
    monkeypatch.setattr(chat_route, "resolve_embed_runtime", resolve_embed)

    scopes = await chat_route._resolve_all_vault_scopes(
        session=object(),
        user_id="owner",
    )

    assert [
        (scope.vault_id, scope.vault_name, scope.embed_profile_id, scope.embed_runtime.model)
        for scope in scopes
    ] == [
        (1, "Personal", 7, "embed-model-7"),
        (2, "Work", 8, "embed-model-8"),
    ]


@pytest.mark.asyncio
async def test_all_chat_scopes_require_at_least_one_indexed_vault(monkeypatch):
    async def list_vaults(session, user_id):
        return [
            SimpleNamespace(
                id=1,
                name="Unindexed",
                indexed_at=None,
                embed_profile_id=None,
            )
        ]

    monkeypatch.setattr(chat_route.vault_repo, "list_vaults", list_vaults)

    with pytest.raises(HTTPException) as exc_info:
        await chat_route._resolve_all_vault_scopes(
            session=object(),
            user_id="owner",
        )

    assert exc_info.value.status_code == 409
    assert "没有已索引的知识库" in exc_info.value.detail
