"""Repository — vault / user 数据访问（仅 SQL/ORM 读写，不含业务规则）。

能力：
- vault 的增删查（归属 user_id 隔离）
- user 的增查（多用户模式，ENABLE_MULTIUSER=true）

主要函数：
- async def create_vault(session, user_id, name, source_type, source_value, filters, origin="ui") -> Vault
- async def get_vault(session, vault_id, user_id) -> Vault | None
- async def list_vaults(session, user_id) -> list[Vault]
- async def count_vaults(session) -> int                       # 判定是否需要注入 .env 种子（§17.2）
- async def find_by_source(session, user_id, source_value) -> Vault | None  # 无头模式对账用
- async def delete_vault(session, vault_id, user_id) -> None
- async def create_user(session, username, password_hash, is_admin=False) -> User
- async def get_user_by_username(session, username) -> User | None

关联方案：docs/design.md §17.2（vault）/ §17.3（user）/ §17.4（数据模型）。
"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Vault, User


async def create_vault(
    session: AsyncSession,
    user_id: str,
    name: str,
    source_type: str,
    source_value: str,
    filters_json: str = "{}",
    origin: str = "ui",          # ui | env，见 §17.2 种子规则
) -> Vault:
    ...


async def count_vaults(session: AsyncSession) -> int:
    # SELECT COUNT(*) FROM vaults —— 为空时才注入 .env 种子（避免用户删除后被复活）
    ...


async def find_by_source(
    session: AsyncSession, user_id: str, source_value: str
) -> Optional[Vault]:
    # 按 source_value 查重；无头模式（UI_ENABLED=false）每次启动据此对账
    ...


async def get_vault(
    session: AsyncSession, vault_id: int, user_id: str
) -> Optional[Vault]:
    ...


async def list_vaults(session: AsyncSession, user_id: str) -> List[Vault]:
    ...


async def delete_vault(session: AsyncSession, vault_id: int, user_id: str) -> None:
    # 同时清理该 vault 下的 notes / chunks 行（向量库清理在 vault_service 编排）
    ...


async def create_user(
    session: AsyncSession,
    username: str,
    password_hash: str,
    is_admin: bool = False,
) -> User:
    ...


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    ...
