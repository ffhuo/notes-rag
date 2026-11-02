from types import SimpleNamespace

import pytest

from app.api.routes.vaults import _file_index_status
from app.core import database
from app.core.config import settings
from app.models import Chunk, Note, Vault
from app.models.schemas import IngestFilters
from app.repositories import note_repo, vault_repo
from app.services.sync_service import scan_files


@pytest.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "test.db"))
    await database.close_database_engine()
    await database.create_database_engine()
    await database.init_db()
    yield
    await database.close_database_engine()


def test_scan_files_uses_ingest_filters(tmp_path):
    root = tmp_path / "vault"
    (root / "private").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "note.md").write_text("note")
    (root / "private" / "secret.md").write_text("secret")
    (root / ".git" / "hidden.md").write_text("hidden")
    (root / "ignored.txt").write_text("not markdown")
    (root / "large.md").write_text("x" * 100)

    config = SimpleNamespace(
        ingest_exts=["md"],
        ingest_exclude_dirs=[".git"],
        max_file_size=1024,
    )
    filters = IngestFilters(exclude=["private/**"], max_file_size=64)

    files, scan_complete = scan_files(root, filters, config)

    assert scan_complete is True
    assert set(files) == {"note.md"}


def test_file_index_status_uses_current_and_latest_run_state():
    note = SimpleNamespace(size_bytes=12, mtime_ns=34)

    assert _file_index_status("note.md", 12, 34, note, None, set()) == "indexed"
    assert _file_index_status("note.md", 13, 34, note, None, set()) == "pending"
    assert _file_index_status("new.md", 12, 34, None, None, set()) == "pending"
    assert _file_index_status("note.md", 12, 34, note, None, {"note.md"}) == "error"
    assert _file_index_status("note.md", 12, 34, note, "note.md", {"note.md"}) == "indexing"


@pytest.mark.asyncio
async def test_indexed_counts_are_grouped_by_vault(db):
    async with database.session_scope() as session:
        first = await vault_repo.create_vault(
            session, user_id="default", name="first", source_type="local", source_value="/first"
        )
        second = await vault_repo.create_vault(
            session, user_id="default", name="second", source_type="local", source_value="/second"
        )
        note = Note(
            vault_id=first.id, user_id="default", file_path="a.md", title="a",
            size_bytes=1, mtime_ns=1, content_hash="hash",
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)
        session.add_all(
            [
                Chunk(
                    user_id="default", vault_id=first.id, note_id=note.id, idx=index,
                    content="text", char_start=index, char_end=index + 1,
                    vector_id=f"chunk-{index}",
                )
                for index in range(2)
            ]
        )
        await session.commit()

        counts = await note_repo.indexed_counts_by_vault(session, [first.id, second.id])

    assert counts == {first.id: (1, 2), second.id: (0, 0)}
