"""SQLite FTS5 persistence and search for chunk-level BM25 retrieval."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.bm25 import build_fts_query, prepare_index_documents


@dataclass(frozen=True)
class Bm25Hit:
    vector_id: str
    note_id: str
    file_path: str
    title: str
    content: str
    score: float


async def delete_for_note(session: AsyncSession, note_id: int) -> None:
    """Remove indexed terms for chunks that are about to be replaced/deleted."""
    await session.execute(
        text(
            """
            DELETE FROM chunks_bm25
            WHERE rowid IN (SELECT id FROM chunks WHERE note_id = :note_id)
            """
        ),
        {"note_id": note_id},
    )


async def delete_for_vault(session: AsyncSession, vault_id: int) -> None:
    """Remove indexed terms for all chunks belonging to a vault."""
    await session.execute(
        text(
            """
            DELETE FROM chunks_bm25
            WHERE rowid IN (SELECT id FROM chunks WHERE vault_id = :vault_id)
            """
        ),
        {"vault_id": vault_id},
    )


async def index_chunks(
    session: AsyncSession,
    documents: list[tuple[int, str, str, str]],
) -> None:
    """Index persisted chunks as pre-tokenized FTS5 documents."""
    if not documents:
        return
    prepared = await asyncio.to_thread(prepare_index_documents, documents)
    await session.execute(
        text(
            """
            INSERT INTO chunks_bm25(rowid, title, file_path, content)
            VALUES (:rowid, :title, :file_path, :content)
            """
        ),
        prepared,
    )


async def reindex_note(session: AsyncSession, note_id: int) -> None:
    """Refresh searchable title/path/content after note metadata changes."""
    await delete_for_note(session, note_id)
    result = await session.execute(
        text(
            """
            SELECT chunks.id, notes.title, notes.file_path, chunks.content
            FROM chunks
            JOIN notes ON notes.id = chunks.note_id
            WHERE notes.id = :note_id
            ORDER BY chunks.id
            """
        ),
        {"note_id": note_id},
    )
    await index_chunks(session, list(result.tuples()))


async def search(
    session: AsyncSession,
    query: str,
    vault_id: int,
    limit: int,
) -> list[Bm25Hit]:
    """Return BM25-ranked chunks restricted to one vault."""
    fts_query = await asyncio.to_thread(build_fts_query, query)
    if fts_query is None or limit <= 0:
        return []

    result = await session.execute(
        text(
            """
            SELECT
                chunks.vector_id,
                chunks.note_id,
                notes.file_path,
                notes.title,
                chunks.content,
                bm25(chunks_bm25, 4.0, 2.0, 1.0) AS bm25_score
            FROM chunks_bm25
            JOIN chunks ON chunks.id = chunks_bm25.rowid
            JOIN notes ON notes.id = chunks.note_id
            WHERE chunks_bm25 MATCH :query
              AND chunks.vault_id = :vault_id
            ORDER BY bm25_score ASC
            LIMIT :limit
            """
        ),
        {"query": fts_query, "vault_id": vault_id, "limit": limit},
    )
    return [
        Bm25Hit(
            vector_id=row.vector_id,
            note_id=str(row.note_id),
            file_path=row.file_path,
            title=row.title,
            content=row.content,
            score=float(row.bm25_score),
        )
        for row in result
    ]
