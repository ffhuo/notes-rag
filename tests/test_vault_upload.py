"""上传型 vault 的「更新文件」能力 — 锁定整包替换与失败保护。

背景：uploaded vault 的文件只存在于服务端解压副本里，用户在本地改完文件后
无法靠 sync 感知（服务端看到的永远是上次解压的内容），必须重新上传整包替换。
本文件固化三件事：
1. 重新上传 = 整包替换（旧包独有的文件必须消失，否则索引里会残留幽灵笔记）
2. 新包非法/穿越时，旧目录原样保留（先解压到临时目录，成功后才换）
3. 接口约束：仅 uploaded 可替换、作业运行中 409、跨用户 404

关联方案：M06 §5.3（vault 实体 / 源类型）；M03 §5.13（异步作业）。
"""
import io
import zipfile

import pytest
from fastapi import HTTPException

from app.api.routes.vaults import replace_upload
from app.core import database
from app.core.config import settings
from app.models import SyncRun, Vault
from app.repositories import vault_repo
from app.services import vault_service


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """临时 SQLite + 临时上传目录（避免碰到开发机的 data/uploads）。"""
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    await database.close_database_engine()
    await database.create_database_engine()
    await database.init_db()
    yield
    await database.close_database_engine()


class _Upload:
    """够 save_upload 用的最小 UploadFile 替身（只读 read() 与 filename）。"""

    def __init__(self, data: bytes, filename: str = "vault.zip"):
        self._data = data
        self.filename = filename

    async def read(self) -> bytes:
        return self._data


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


async def _seed_vault(source_type: str = "uploaded", user_id: str = "default") -> int:
    async with database.session_scope() as session:
        vault = await vault_repo.create_vault(
            session, user_id=user_id, name="v", source_type=source_type, source_value=""
        )
        return vault.id


@pytest.mark.asyncio
async def test_save_upload_replaces_whole_directory(db):
    """第二次上传后，只在旧包里出现的文件必须消失（整包替换，不是合并）。"""
    vid = await _seed_vault()
    await vault_service.save_upload(vid, _Upload(_zip({"a.md": "A", "old.md": "OLD"})))
    target = vault_service.resolve_local_path(
        await _get_vault(vid), settings
    )
    assert (target / "old.md").exists()

    await vault_service.save_upload(vid, _Upload(_zip({"a.md": "A2", "b.md": "B"})))

    assert (target / "a.md").read_text(encoding="utf-8") == "A2"
    assert (target / "b.md").exists()
    assert not (target / "old.md").exists()
    # 临时目录不能残留
    assert not list(target.parent.glob(f".{target.name}.uploading-*"))


@pytest.mark.asyncio
async def test_save_upload_keeps_old_files_when_zip_is_illegal(db):
    """新包含穿越条目 → 400 级的 ValueError，且旧目录不能被清空。"""
    vid = await _seed_vault()
    await vault_service.save_upload(vid, _Upload(_zip({"keep.md": "KEEP"})))
    target = vault_service.resolve_local_path(await _get_vault(vid), settings)

    bad = _zip({"../evil.md": "x"})
    with pytest.raises(ValueError, match="非法路径"):
        await vault_service.save_upload(vid, _Upload(bad))

    assert (target / "keep.md").read_text(encoding="utf-8") == "KEEP"
    assert not list(target.parent.glob(f".{target.name}.uploading-*"))


@pytest.mark.asyncio
async def test_replace_upload_endpoint_updates_uploaded_vault(db):
    vid = await _seed_vault()
    await vault_service.save_upload(vid, _Upload(_zip({"a.md": "A"})))

    async with database.session_scope() as session:
        out = await replace_upload(
            vid, _Upload(_zip({"a.md": "A2"})), user_id="default",
            session=session, settings=settings,
        )

    assert out.id == vid
    target = vault_service.resolve_local_path(await _get_vault(vid), settings)
    assert (target / "a.md").read_text(encoding="utf-8") == "A2"


@pytest.mark.asyncio
async def test_replace_upload_rejects_local_vault(db):
    """local 指向用户自己的目录，服务端不能替它换文件。"""
    vid = await _seed_vault(source_type="local")

    async with database.session_scope() as session:
        with pytest.raises(HTTPException) as exc:
            await replace_upload(
                vid, _Upload(_zip({"a.md": "A"})), user_id="default",
                session=session, settings=settings,
            )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_replace_upload_rejects_when_job_running(db):
    """作业扫描目录期间换文件会得到自相矛盾的对账结果 → 409。"""
    vid = await _seed_vault()
    async with database.session_scope() as session:
        session.add(SyncRun(user_id="default", vault_id=vid, trigger="manual", mode="sync"))
        await session.commit()

    async with database.session_scope() as session:
        with pytest.raises(HTTPException) as exc:
            await replace_upload(
                vid, _Upload(_zip({"a.md": "A"})), user_id="default",
                session=session, settings=settings,
            )
    assert exc.value.status_code == 409
    assert exc.value.detail["existing_run_id"]


@pytest.mark.asyncio
async def test_replace_upload_isolated_by_user(db):
    """别人的 vault 不能被替换（按 user_id 隔离，返回 404 而非 403）。"""
    vid = await _seed_vault(user_id="u1")

    async with database.session_scope() as session:
        with pytest.raises(HTTPException) as exc:
            await replace_upload(
                vid, _Upload(_zip({"a.md": "A"})), user_id="u2",
                session=session, settings=settings,
            )
    assert exc.value.status_code == 404


async def _get_vault(vault_id: int) -> Vault:
    async with database.session_scope() as session:
        return await vault_repo.get_vault(session, vault_id, "default")
