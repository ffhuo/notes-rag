"""数据访问·模型配置 — model_profiles 表的 CRUD（多模型管理，见 design.md §18）。

能力：
- 一个用户可配置多个 LLM（kind='llm'）与多个 Embedding（kind='embed'），使用时按 name / id 选择
- 每个 kind 下有且仅有一个默认项（is_default），由 set_default 保证唯一
- 供 model_service 做「请求参数 → 用户默认 → 系统种子」三级解析

主要函数：
- async def create_profile(session, user_id, data: ModelProfileCreate) -> ModelProfile
- async def get_profile(session, profile_id, user_id) -> ModelProfile | None
- async def find_by_name(session, user_id, kind, name) -> ModelProfile | None
- async def list_profiles(session, user_id, kind=None, only_enabled=False) -> list[ModelProfile]
- async def get_default(session, user_id, kind) -> ModelProfile | None   # is_default=True 的那条
- async def update_profile(session, profile, patch: dict) -> ModelProfile
- async def set_default(session, profile) -> None    # 同 (user_id, kind) 内其余置 False
- async def delete_profile(session, profile) -> None
- async def count_profiles(session, kind=None) -> int   # 判空，供种子注入使用

关联方案：docs/design.md §18.1（数据模型）、§18.3（解析优先级）、§18.4（种子规则）。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ModelProfile


async def create_profile(
    session: AsyncSession,
    user_id: str,
    kind: str,
    name: str,
    model: str,
    provider: str = "openai",
    base_url: str = "",
    api_key: str = "",
    params_json: str = "{}",
    is_default: bool = False,
    origin: str = "ui",
) -> ModelProfile:
    ...


async def get_profile(
    session: AsyncSession, profile_id: int, user_id: str
) -> ModelProfile | None:
    ...


async def find_by_name(
    session: AsyncSession, user_id: str, kind: str, name: str
) -> ModelProfile | None:
    ...


async def list_profiles(
    session: AsyncSession,
    user_id: str,
    kind: str | None = None,
    only_enabled: bool = False,
) -> list[ModelProfile]:
    ...


async def get_default(
    session: AsyncSession, user_id: str, kind: str
) -> ModelProfile | None:
    ...


async def update_profile(
    session: AsyncSession, profile: ModelProfile, patch: dict
) -> ModelProfile:
    ...


async def set_default(session: AsyncSession, profile: ModelProfile) -> None:
    # 同一 (user_id, kind) 内：先把所有 is_default 置 False，再把目标置 True
    ...


async def delete_profile(session: AsyncSession, profile: ModelProfile) -> None:
    ...


async def count_profiles(session: AsyncSession, kind: str | None = None) -> int:
    ...
