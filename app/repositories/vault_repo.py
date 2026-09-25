"""Repository — vault / user 数据访问（仅 SQL/ORM 读写，不含业务规则）。

能力：
- vault 的增删查（归属 user_id 隔离）
- user 的增查（多用户模式，ENABLE_MULTIUSER=true）

主要函数：
- async def create_vault(session, user_id, name, source_type, source_value, filters_json, origin="ui") -> Vault
- async def get_vault(session, vault_id, user_id) -> Vault | None
- async def list_vaults(session, user_id) -> list[Vault]
- async def count_vaults(session) -> int                       # 统计用（如诊断 / 运维视图）
- async def find_by_source(session, user_id, source_value) -> Vault | None  # 幂等建库 / 无头模式对账
- async def delete_vault(session, vault_id, user_id) -> None
- async def create_user(session, username, password_hash, is_admin=False) -> User
- async def get_user_by_username(session, username) -> User | None

**契约**：所有 vault 查询函数**必须**带 `user_id`（无默认值）—— 把「忘记隔离」从
静默越权变成调用方立刻可见的类型错误（同 M02 §9）。

关联方案：M06 §5.4（repo 接口）/ §5.5（API 契约）；M02 §5.3（表结构）；M03 §5.11（sync_runs）。
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
    origin: str = "ui",          # 一期恒为 "ui"（.env 种子注入机制已废弃，保留列仅为历史兼容）
) -> Vault:
    ...


async def count_vaults(session: AsyncSession) -> int:
    # SELECT COUNT(*) FROM vaults —— 供诊断 / 运维视图；**不再**用于「表空则注入 .env 种子」
    # （vault 完全由 DB/API/前端运行时配置，.env 不提供种子，见 M06 §5.2）
    ...


async def find_by_source(
    session: AsyncSession, user_id: str, source_value: str
) -> Optional[Vault]:
    # 按 (user_id, source_value) 查重：/ingest 幂等建库（同源不重复建 vault）走这里
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
