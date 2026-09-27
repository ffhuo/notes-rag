"""数据访问·笔记 — notes / chunks 表的 CRUD。

能力：
- 笔记与分块元数据的写入（按 **(vault_id, file_path)** 唯一去重）
- 对账用：一次取回某 vault 的全部已知路径（known 集合），避免逐文件查询
- 文件级替换写入：先删该 note 的 chunks 行，再插新行（**不可**按 idx upsert）
- 维护 vector_id，使 SQLite 与向量库一一对应

主要函数：
- list_note_paths(session, vault_id) -> dict[str, Note]: 对账的 known 集合 {相对路径: Note}
- upsert_note(session, vault_id, rel_path, title, size_bytes, mtime_ns, content_hash, user_id) -> Note
- replace_chunks(session, note_id, chunks) -> None: 文件级替换
- get_note_by_path(session, vault_id, rel_path) -> Note | None
- delete_note_cascade(session, note_id) -> None: 删 chunks + notes
- delete_chunks_by_note(session, note_id) -> list[str]: 删分块，返回被删的 vector_id 列表
- list_chunks_by_vault(session, vault_id) -> list[Chunk]

关键约定：
- `file_path` 存**相对 vault 根的 POSIX 相对路径**，不是绝对路径
- 向量的增删**不在本模块**：repo 只碰 SQLite，Chroma 由 service 调用 vectorstore

关联方案：docs/design.md §6（数据模型）、§10（手写 TODO 地图）。
"""
from dataclasses import dataclass

from sqlalchemy import select, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Note, Chunk


@dataclass
class ChunkRecord:
    """chunks 行的纯数据契约（service 层只组装数据，不接触 ORM 实体）。

    持久化时由 replace_chunks 转换为 Chunk；vault_id / note_id 由调用方提供。
    """

    vault_id: int
    idx: int
    content: str
    char_start: int
    char_end: int
    vector_id: str
    user_id: str = "default"
    embed_profile_id: int | None = None


async def list_note_paths(session: AsyncSession, vault_id: int) -> dict[str, Note]:
    """取某 vault 的全部笔记，返回 {相对路径: Note}。对账的 known 集合。"""
    result = await session.execute(
        select(Note).where(Note.vault_id == vault_id)
    )
    return {n.file_path: n for n in result.scalars().all()}


async def upsert_note(
    session: AsyncSession,
    vault_id: int,
    rel_path: str,
    title: str,
    size_bytes: int,
    mtime_ns: int,
    content_hash: str,
    user_id: str,
) -> Note:
    """写入 / 更新一条笔记元数据（含变更判据字段），返回 Note。

    user_id 必填且与 vault.user_id 一致：历史版本漏写该字段（落为 "default"），
    导致 delete_vault 按 user_id 过滤时整片漏删；这里对已存在的行也回写修正。

    本函数只负责 notes 行；chunks 行请用 replace_chunks()。
    """
    existing = await session.execute(
        select(Note).where(
            Note.vault_id == vault_id,
            Note.file_path == rel_path,
        )
    )
    note = existing.scalar_one_or_none()

    if note is not None:
        # 更新已有记录
        note.title = title
        note.size_bytes = size_bytes
        note.mtime_ns = mtime_ns
        note.content_hash = content_hash
        note.user_id = user_id          # 修正历史残留归属（旧版本未写入）
    else:
        # 新建记录
        note = Note(
            user_id=user_id,
            vault_id=vault_id,
            file_path=rel_path,
            title=title,
            size_bytes=size_bytes,
            mtime_ns=mtime_ns,
            content_hash=content_hash,
        )
        session.add(note)

    await session.commit()
    await session.refresh(note)
    return note


async def replace_chunks(session: AsyncSession, note_id: int, chunks: list[ChunkRecord]) -> None:
    """文件级替换：先删该 note 的旧 chunks 行，再按 ChunkRecord 插新行。

    **不可**改成「按 idx upsert」—— 文件变短时高序号的旧行不会被覆盖，
    会留下检索仍能命中的幽灵内容（M03 ADR-8）。
    """
    await session.execute(
        sa_delete(Chunk).where(Chunk.note_id == note_id)
    )
    for rec in chunks:
        session.add(
            Chunk(
                user_id=rec.user_id,
                vault_id=rec.vault_id,
                note_id=note_id,
                idx=rec.idx,
                content=rec.content,
                char_start=rec.char_start,
                char_end=rec.char_end,
                vector_id=rec.vector_id,
                embed_profile_id=rec.embed_profile_id,
            )
        )
    await session.commit()


async def get_note_by_path(session: AsyncSession, vault_id: int, rel_path: str) -> Note | None:
    """按 (vault_id, 相对路径) 取笔记。"""
    result = await session.execute(
        select(Note).where(
            Note.vault_id == vault_id,
            Note.file_path == rel_path,
        )
    )
    return result.scalar_one_or_none()


async def delete_note_cascade(session: AsyncSession, note_id: int) -> None:
    """删除笔记：先删其 chunks 行，再删 notes 行（对应向量的清理由 service 层处理）。"""
    await session.execute(
        sa_delete(Chunk).where(Chunk.note_id == note_id)
    )
    await session.execute(
        sa_delete(Note).where(Note.id == note_id)
    )
    await session.commit()


async def delete_chunks_by_note(session: AsyncSession, note_id: int) -> list[str]:
    """只删某笔记的全部分块，返回被删的 vector_id 列表（供向量库清理）。"""
    result = await session.execute(
        select(Chunk.vector_id).where(Chunk.note_id == note_id)
    )
    vector_ids = list(result.scalars().all())

    await session.execute(
        sa_delete(Chunk).where(Chunk.note_id == note_id)
    )
    await session.commit()
    return vector_ids


async def list_chunks_by_vault(session: AsyncSession, vault_id: int) -> list[Chunk]:
    """取某 vault 的全部分块，供一致性自检比对（M03 §5.12）。"""
    result = await session.execute(
        select(Chunk).where(Chunk.vault_id == vault_id)
    )
    return list(result.scalars().all())


async def list_vector_ids_by_note(session: AsyncSession, note_id: int) -> list[str]:
    """只读取某笔记全部分块的 vector_id（不删除），供改名时更新向量元数据。"""
    result = await session.execute(
        select(Chunk.vector_id).where(Chunk.note_id == note_id)
    )
    return list(result.scalars().all())


async def update_note_path(session: AsyncSession, note_id: int, new_rel_path: str) -> None:
    """改名/移动：只更新 notes.file_path（内容与向量不变，零 embedding）。"""
    note = await session.get(Note, note_id)
    if note is None:
        return
    note.file_path = new_rel_path
    await session.commit()


async def clear_vault(session: AsyncSession, vault_id: int) -> list[str]:
    """清空某 vault 的全部 notes + chunks（rebuild 用），返回被清的全部 vector_id。

    对应向量的清理由 service 层按 collection 处理。
    """
    result = await session.execute(
        select(Chunk.vector_id).where(Chunk.vault_id == vault_id)
    )
    vector_ids = list(result.scalars().all())

    note_ids = await session.execute(
        select(Note.id).where(Note.vault_id == vault_id)
    )
    ids = list(note_ids.scalars().all())
    if ids:
        await session.execute(sa_delete(Chunk).where(Chunk.vault_id == vault_id))
        await session.execute(sa_delete(Note).where(Note.vault_id == vault_id))
    await session.commit()
    return vector_ids
