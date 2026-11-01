"""Chinese-aware tokenization helpers for the SQLite FTS5 BM25 index."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any

import jieba
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


_TOKEN_PATTERN = re.compile(r"[\w+#&.-]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Split Chinese and mixed-language text into terms shared by index/query."""
    terms: list[str] = []
    for raw_term in jieba.cut(text, cut_all=False):
        term = raw_term.strip().lower()
        if term and _TOKEN_PATTERN.fullmatch(term) and any(char.isalnum() for char in term):
            terms.append(term)
    return terms


def tokenize_for_index(text: str) -> str:
    """Prepare text for FTS5's unicode tokenizer using jieba word boundaries."""
    return " ".join(tokenize(text))


def build_fts_query(query: str) -> str | None:
    """Build a safe OR query so any segmented term can contribute to ranking."""
    terms = list(dict.fromkeys(tokenize(query)))
    if not terms:
        return None
    return " OR ".join(f'"{term}"' for term in terms)


def prepare_index_documents(
    documents: Sequence[tuple[int, str, str, str]],
) -> list[dict[str, Any]]:
    """Tokenize (chunk id, title, path, content) rows for FTS5 insertion."""
    return [
        {
            "rowid": chunk_id,
            "title": tokenize_for_index(title),
            "file_path": tokenize_for_index(file_path),
            "content": tokenize_for_index(content),
        }
        for chunk_id, title, file_path, content in documents
    ]


async def ensure_index(connection: AsyncConnection) -> None:
    """Create the FTS index and backfill existing chunks once per index version."""
    await connection.exec_driver_sql(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_bm25
        USING fts5(title, file_path, content, tokenize='unicode61 remove_diacritics 2')
        """
    )
    await connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS bm25_index_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    result = await connection.execute(
        text("SELECT value FROM bm25_index_state WHERE key = 'schema_version'")
    )
    if result.scalar_one_or_none() == "1":
        return

    await connection.exec_driver_sql("DELETE FROM chunks_bm25")
    result = await connection.exec_driver_sql(
        """
        SELECT chunks.id, notes.title, notes.file_path, chunks.content
        FROM chunks
        JOIN notes ON notes.id = chunks.note_id
        ORDER BY chunks.id
        """
    )
    while rows := result.fetchmany(500):
        documents = await asyncio.to_thread(prepare_index_documents, rows)
        await connection.execute(
            text(
                """
                INSERT INTO chunks_bm25(rowid, title, file_path, content)
                VALUES (:rowid, :title, :file_path, :content)
                """
            ),
            documents,
        )
    await connection.execute(
        text(
            """
            INSERT INTO bm25_index_state(key, value)
            VALUES ('schema_version', '1')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
        )
    )
