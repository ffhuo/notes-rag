"""数据访问·笔记 — notes / chunks 表的 CRUD。

能力：
- 笔记与分块元数据的写入（按 **(vault_id, file_path)** 唯一去重）
- 对账用：一次取回某 vault 的全部已知路径（known 集合），避免逐文件查询
- 文件级替换写入：先删该 note 的 chunks 行，再插新行（**不可**按 idx upsert）
- 维护 vector_id，使 SQLite 与向量库一一对应

主要函数：
- list_note_paths(session, vault_id) -> dict[str, Note]: 对账的 known 集合 {相对路径: Note}
- upsert_note(session, vault_id, rel_path, title, size_bytes, mtime_ns, content_hash) -> Note
- get_note_by_path(session, vault_id, rel_path) -> Note | None: 按相对路径取笔记
- delete_note_cascade(session, note_id) -> None: 删该 note 的 chunks 行 + notes 行
- delete_chunks_by_note(session, note_id) -> None: 只删分块（向量由 service 在 repo 之外删）

关键约定：
- `file_path` 存**相对 vault 根的 POSIX 相对路径**，不是绝对路径 ——
  否则 vault 目录改名 / 搬家会被对账误判为「整库删除 + 整库新增」。
- 向量的增删**不在本模块**：repo 只碰 SQLite，Chroma 由 service 调用 vectorstore
  （见 M02 §5.3 删除语义 / M03 ADR-8 文件级替换）。

关联方案：docs/design.md §6（数据模型）、§10（手写 TODO 地图）。
变更管理（对账 / 判据 / 替换写入）详见设计文档库 M03 §5.8–§5.9。
"""
from sqlalchemy.ext.asyncio import AsyncSession


async def list_note_paths(session: AsyncSession, vault_id: int) -> dict:
    """取某 vault 的全部笔记，返回 {相对路径: Note}。对账的 known 集合。"""
    ...


async def upsert_note(
    session: AsyncSession,
    vault_id: int,
    rel_path: str,
    title: str,
    size_bytes: int,
    mtime_ns: int,
    content_hash: str,
):
    """写入 / 更新一条笔记元数据（含变更判据字段），返回 Note。

    注意：本函数只负责 notes 行；chunks 行请用 replace_chunks()。
    """
    ...


async def replace_chunks(session: AsyncSession, note_id: int, chunks: list) -> None:
    """文件级替换：先删该 note 的旧 chunks 行，再插新行。

    **不可**改成「按 idx upsert」—— 文件变短时高序号的旧行不会被覆盖，
    会留下检索仍能命中的幽灵内容（M03 ADR-8）。
    """
    ...


async def get_note_by_path(session: AsyncSession, vault_id: int, rel_path: str):
    """按 (vault_id, 相对路径) 取笔记。"""
    ...


async def delete_note_cascade(session: AsyncSession, note_id: int) -> None:
    """删除笔记：先删其 chunks 行，再删 notes 行（对应向量的清理见 M03 §5.9.2）。"""
    ...


async def delete_chunks_by_note(session: AsyncSession, note_id: int) -> None:
    """只删某笔记的全部分块（返回被删的 vector_id 列表，供向量库清理）。"""
    ...


async def list_chunks_by_vault(session: AsyncSession, vault_id: int) -> list:
    """取某 vault 的全部分块，供一致性自检比对（M03 §5.12）。"""
    ...
