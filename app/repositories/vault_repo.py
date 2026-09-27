"""Repository — vault / user 数据访问（仅 SQL/ORM 读写，不含业务规则）。

能力：
- vault 的增删查（归属 user_id 隔离）
- user 的增查（多用户模式，ENABLE_MULTIUSER=true）

主要函数：
- async def create_vault(session, user_id, name, source_type, source_value, filters_json, origin="ui") -> Vault
- async def get_vault(session, vault_id, user_id) -> Vault | None
- async def list_vaults(session, user_id) -> list[Vault]
- async def update_vault(session, vault_id, user_id, name=None, filters_json=None) -> Vault | None
- async def count_vaults(session) -> int
- async def find_by_source(session, user_id, source_value) -> Vault | None
- async def delete_vault(session, vault_id, user_id) -> None
- async def create_user(session, username, password_hash, is_admin=False) -> User
- async def get_user_by_username(session, username) -> User | None

**契约**：所有 vault 查询函数**必须**带 `user_id`（无默认值）—— 把「忘记隔离」从
静默越权变成调用方立刻可见的类型错误（同 M02 §9）。

关联方案：M06 §5.4（repo 接口）/ §5.5（API 契约）；M02 §5.3（表结构）；M03 §5.11（sync_runs）。
"""
from datetime import datetime, timezone
from typing import List, Optional
import json

from sqlalchemy import select, delete as sa_delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Vault, User, Note, Chunk


async def create_vault(
    session: AsyncSession,
    user_id: str,
    name: str,
    source_type: str,
    source_value: str,
    filters_json: str = "{}",
    origin: str = "ui",
) -> Vault:
    vault = Vault(
        user_id=user_id,
        name=name,
        source_type=source_type,
        source_value=source_value,
        filters_json=filters_json,
        origin=origin,
    )
    session.add(vault)
    await session.commit()
    await session.refresh(vault)
    return vault


async def count_vaults(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Vault))
    return result.scalar_one()


async def update_vault(
    session: AsyncSession,
    vault_id: int,
    user_id: str,
    name: Optional[str] = None,
    filters_json: Optional[str] = None,
) -> Optional[Vault]:
    """改 vault 的 name / filters_json（None = 该字段不动）。

    source_type / source_value 不在此列：换源应新建 vault（见 schemas.VaultUpdate）。
    vault 不存在或不属于该用户 → 返回 None（调用方翻译成 404）。
    """
    vault = await get_vault(session, vault_id, user_id)
    if vault is None:
        return None
    if name is not None:
        vault.name = name
    if filters_json is not None:
        vault.filters_json = filters_json
    await session.commit()
    await session.refresh(vault)
    return vault


async def find_by_source(
    session: AsyncSession, user_id: str, source_value: str
) -> Optional[Vault]:
    result = await session.execute(
        select(Vault).where(
            Vault.user_id == user_id,
            Vault.source_value == source_value,
        )
    )
    return result.scalar_one_or_none()


async def get_vault(
    session: AsyncSession, vault_id: int, user_id: str
) -> Optional[Vault]:
    result = await session.execute(
        select(Vault).where(
            Vault.id == vault_id,
            Vault.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_vaults(session: AsyncSession, user_id: str) -> List[Vault]:
    result = await session.execute(
        select(Vault).where(Vault.user_id == user_id).order_by(Vault.id)
    )
    return list(result.scalars().all())


async def list_all_vaults(session: AsyncSession) -> List[Vault]:
    """列举全部 vault（不限用户）。仅供后台定时 / 维护任务使用，API 请求路径禁用。"""
    result = await session.execute(select(Vault).order_by(Vault.id))
    return list(result.scalars().all())


async def touch_embed_state(
    session: AsyncSession,
    vault_id: int,
    user_id: str,
    profile_id: Optional[int],
) -> bool:
    """作业成功收尾时回写 vault 的 embedding 状态与 indexed_at（M06 ADR-9）。

    - profile_id 为 int：记入 embed_indexed_profiles 并置为当前 embed_profile_id
    - profile_id 为 None（历史 env 占位，已废弃，仅为兼容存量数据）：只刷新 indexed_at，不改模型列
    - vault 不存在 / 归属不符：返回 False（调用方据此仅记日志）
    """
    vault = await get_vault(session, vault_id, user_id)
    if vault is None:
        return False

    if profile_id is not None:
        indexed = json.loads(vault.embed_indexed_profiles or "[]")
        if profile_id not in indexed:
            indexed.append(profile_id)
        vault.embed_indexed_profiles = json.dumps(indexed)
        vault.embed_profile_id = profile_id
    vault.indexed_at = datetime.now(timezone.utc)
    await session.commit()
    return True


async def delete_vault(session: AsyncSession, vault_id: int, user_id: str) -> None:
    """删除 vault 及其关联 notes / chunks 行。"""
    # 先删 chunks（外键关联 note_id）
    note_ids = select(Note.id).where(Note.vault_id == vault_id, Note.user_id == user_id)
    await session.execute(
        sa_delete(Chunk).where(Chunk.note_id.in_(note_ids))
    )
    # 再删 notes
    await session.execute(
        sa_delete(Note).where(Note.vault_id == vault_id, Note.user_id == user_id)
    )
    # 最后删 vault
    await session.execute(
        sa_delete(Vault).where(Vault.id == vault_id, Vault.user_id == user_id)
    )
    await session.commit()


async def create_user(
    session: AsyncSession,
    username: str,
    password_hash: str,
    is_admin: bool = False,
) -> User:
    user = User(
        username=username,
        password_hash=password_hash,
        is_admin=is_admin,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    result = await session.execute(
        select(User).where(User.username == username)
    )
    return result.scalar_one_or_none()
