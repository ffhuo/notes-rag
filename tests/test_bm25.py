import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.core.database import Base
from app.models import Chunk, Note, Vault
from app.rag.bm25 import build_fts_query, ensure_index, tokenize
from app.repositories import bm25_repo, note_repo
from app.repositories.note_repo import ChunkRecord


def test_chinese_query_is_tokenized_into_fts_terms():
    assert tokenize("如何提升检索准确度") == ["如何", "提升", "检索", "准确度"]
    assert build_fts_query("如何提升检索准确度") == (
        '"如何" OR "提升" OR "检索" OR "准确度"'
    )


def test_hybrid_retrieval_defaults_bound_each_candidate_pool():
    settings = Settings(_env_file=None)
    assert settings.bm25_enabled is True
    assert (
        settings.vector_recall_multiplier,
        settings.vector_recall_min,
        settings.vector_recall_max,
    ) == (4, 20, 100)
    assert (
        settings.bm25_recall_multiplier,
        settings.bm25_recall_min,
        settings.bm25_recall_max,
    ) == (4, 20, 100)
    assert (
        settings.rerank_candidate_multiplier,
        settings.rerank_candidate_min,
        settings.rerank_candidate_max,
    ) == (4, 20, 100)
    assert settings.retrieval_rrf_k == 60


def test_hybrid_retrieval_rejects_invalid_candidate_bounds():
    with pytest.raises(ValidationError, match="bm25_recall_min must not exceed bm25_recall_max"):
        Settings(_env_file=None, bm25_recall_min=30, bm25_recall_max=20)


async def test_chunk_replacement_updates_bm25_index(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bm25.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await ensure_index(connection)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        vault = Vault(
            user_id="user-a",
            name="Research",
            source_type="local",
            source_value="/notes",
        )
        session.add(vault)
        await session.commit()
        await session.refresh(vault)

        note = Note(
            user_id="user-a",
            vault_id=vault.id,
            file_path="retrieval.md",
            title="检索质量",
            size_bytes=100,
            mtime_ns=1,
            content_hash="old",
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)

        await note_repo.replace_chunks(
            session,
            note.id,
            [
                ChunkRecord(
                    user_id="user-a",
                    vault_id=vault.id,
                    idx=0,
                    content="向量检索能够找到语义相似的知识片段。",
                    char_start=0,
                    char_end=20,
                    vector_id="chunk-old",
                )
            ],
        )
        old_hits = await bm25_repo.search(session, "向量知识片段", vault.id, 10)
        assert [hit.content for hit in old_hits] == [
            "向量检索能够找到语义相似的知识片段。"
        ]

        await note_repo.replace_chunks(
            session,
            note.id,
            [
                ChunkRecord(
                    user_id="user-a",
                    vault_id=vault.id,
                    idx=0,
                    content="BM25关键词搜索会匹配精确术语。",
                    char_start=0,
                    char_end=18,
                    vector_id="chunk-new",
                )
            ],
        )
        assert await bm25_repo.search(session, "向量知识片段", vault.id, 10) == []
        new_hits = await bm25_repo.search(session, "BM25关键词", vault.id, 10)
        assert [hit.content for hit in new_hits] == ["BM25关键词搜索会匹配精确术语。"]

        await note_repo.update_note_path(session, note.id, "renamed.md")
        assert await bm25_repo.search(session, "retrieval", vault.id, 10) == []
        assert (await bm25_repo.search(session, "renamed", vault.id, 10))[0].file_path == "renamed.md"

        await note_repo.upsert_note(
            session,
            vault_id=vault.id,
            rel_path="renamed.md",
            title="UniqueDocumentTitle",
            size_bytes=100,
            mtime_ns=2,
            content_hash="new",
            user_id="user-a",
        )
        assert await bm25_repo.search(session, "检索质量", vault.id, 10) == []
        assert (await bm25_repo.search(session, "UniqueDocumentTitle", vault.id, 10))[0].title == "UniqueDocumentTitle"

    await engine.dispose()


async def test_startup_backfills_existing_chunks_once(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy-bm25.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        vault = Vault(
            user_id="user-a",
            name="Legacy",
            source_type="local",
            source_value="/legacy",
        )
        session.add(vault)
        await session.flush()
        note = Note(
            user_id="user-a",
            vault_id=vault.id,
            file_path="legacy.md",
            title="Legacy Search",
            size_bytes=20,
            mtime_ns=1,
            content_hash="legacy",
        )
        session.add(note)
        await session.flush()
        session.add(
            Chunk(
                user_id="user-a",
                vault_id=vault.id,
                note_id=note.id,
                idx=0,
                content="旧数据库中的向量索引说明",
                char_start=0,
                char_end=14,
                vector_id="legacy-vector",
                embed_profile_id=1,
            )
        )
        await session.commit()

    async with engine.begin() as connection:
        await ensure_index(connection)
        await ensure_index(connection)

    async with session_factory() as session:
        hits = await bm25_repo.search(session, "旧数据库向量索引", vault.id, 10)
        assert [hit.vector_id for hit in hits] == ["legacy-vector"]

    await engine.dispose()
