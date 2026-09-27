"""删除 vault 的清理范围 — 锁定「删库时必须一并清掉哪些数据」。

背景：`DELETE /vaults/{id}` 曾经只删 notes / chunks / vaults 行，留下孤儿 sync_runs
（vault id 不复用后永远不会被查询引用）与磁盘上的上传副本。
本文件把清理范围固化成断言，避免回归。

关联方案：M06 §5.4 / §5.5（repo 与 API 契约）；M03 §5.11（sync_runs）。
"""
import pytest
from sqlalchemy import func, select

from app.core import database
from app.core.config import settings
from app.models import Chunk, Note, SyncRun, Vault
from app.models.chat import Conversation
from app.repositories import vault_repo
from app.services import vault_service


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """临时 SQLite：建表 → 用例 → 关闭引擎（避免全局引擎在用例间串库）。"""
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "test.db"))
    await database.close_database_engine()
    await database.create_database_engine()
    await database.init_db()
    yield
    await database.close_database_engine()


async def _count(model) -> int:
    async with database.session_scope() as session:
        result = await session.execute(select(func.count()).select_from(model))
        return result.scalar_one()


async def _seed(
    user_id: str = "default",
    source_type: str = "uploaded",
    source_value: str = "",
    with_conversation: bool = False,
) -> int:
    """造一个「完整」的 vault：notes + chunks + sync_run（可选会话），返回 vault id。"""
    async with database.session_scope() as session:
        vault = await vault_repo.create_vault(
            session, user_id=user_id, name="v", source_type=source_type,
            source_value=source_value,
        )
        vid = vault.id
        note = Note(
            vault_id=vid, user_id=user_id, file_path="a.md", title="a",
            size_bytes=1, mtime_ns=1, content_hash="h",
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)
        session.add(
            Chunk(
                user_id=user_id, vault_id=vid, note_id=note.id, idx=0,
                content="正文", char_start=0, char_end=2, vector_id=f"v{vid}_n{note.id}_c0",
            )
        )
        session.add(SyncRun(user_id=user_id, vault_id=vid, trigger="manual", mode="sync"))
        if with_conversation:
            session.add(Conversation(user_id=user_id, vault_id=vid))
        await session.commit()
        return vid


@pytest.mark.asyncio
async def test_delete_vault_clears_children(db):
    vid = await _seed()

    async with database.session_scope() as session:
        await vault_repo.delete_vault(session, vid, "default")

    assert await _count(Vault) == 0
    assert await _count(Note) == 0
    assert await _count(Chunk) == 0
    # 孤儿作业是本文件存在的直接原因：不删会在任务列表里留下永远无法归属的记录
    assert await _count(SyncRun) == 0


@pytest.mark.asyncio
async def test_conversation_kept_after_vault_delete(db):
    """会话是用户资产：删 vault 不删会话，vault_id 允许悬空（外键当前未开启）。"""
    vid = await _seed(with_conversation=True)

    async with database.session_scope() as session:
        await vault_repo.delete_vault(session, vid, "default")

    assert await _count(Conversation) == 1


@pytest.mark.asyncio
async def test_delete_vault_isolated_by_user(db):
    """别人的 vault 不能被连带删除（user_id 必须进 where）。"""
    vid = await _seed(user_id="u1")

    async with database.session_scope() as session:
        await vault_repo.delete_vault(session, vid, "u2")

    assert await _count(Vault) == 1
    assert await _count(SyncRun) == 1


@pytest.mark.asyncio
async def test_delete_upload_dir_only_for_uploaded(db, tmp_path, monkeypatch):
    """上传副本目录随库删除；local 类型的目录是用户自己的数据，纹丝不动。"""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    uploaded_id = await _seed(source_type="uploaded")
    local_dir = tmp_path / "my-notes"
    local_dir.mkdir()
    (local_dir / "keep.md").write_text("keep", encoding="utf-8")
    local_id = await _seed(source_type="local", source_value=str(local_dir))

    copy_dir = tmp_path / "uploads" / str(uploaded_id)
    copy_dir.mkdir(parents=True)
    (copy_dir / "a.md").write_text("x", encoding="utf-8")

    async with database.session_scope() as session:
        uploaded = await vault_repo.get_vault(session, uploaded_id, "default")
        local = await vault_repo.get_vault(session, local_id, "default")
        await vault_service.delete_upload_dir(uploaded, settings)
        await vault_service.delete_upload_dir(local, settings)

    assert not copy_dir.exists()
    assert (local_dir / "keep.md").exists()


@pytest.mark.asyncio
async def test_delete_upload_dir_tolerates_missing(db, tmp_path, monkeypatch):
    """目录本就不存在时不报错（重复删除 / 上传后从未解压都要能安全通过）。"""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    vid = await _seed(source_type="uploaded")

    async with database.session_scope() as session:
        vault = await vault_repo.get_vault(session, vid, "default")
        await vault_service.delete_upload_dir(vault, settings)

    assert not (tmp_path / "uploads" / str(vid)).exists()
