"""数据访问·笔记 — notes / chunks 表的 CRUD。

能力：
- 笔记与分块元数据的写入（upsert，按 file_path 去重）
- 索引前查重，跳过未变更文件；rebuild 时删除旧分块
- 维护 vector_id，使 SQLite 与向量库一一对应

主要函数：
- upsert_note(session, file_path, title, mtime, chunks) -> None: 写入笔记与分块
- get_note_by_path(session, file_path) -> Note | None: 按路径取笔记
- delete_chunks_by_note(session, note_id) -> None: 删除某笔记的全部分块

关联方案：docs/design.md §6（数据模型）、§10（手写 TODO 地图）。
"""
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_note(
    session: AsyncSession,
    file_path: str,
    title: str,
    mtime: float,
    chunks: list,
) -> None:
    ...


async def get_note_by_path(session: AsyncSession, file_path: str):
    ...


async def delete_chunks_by_note(session: AsyncSession, note_id: int) -> None:
    ...
