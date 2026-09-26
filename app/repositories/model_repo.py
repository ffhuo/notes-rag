"""数据访问·模型配置 — model_profiles 表的 CRUD（多模型管理，见 design.md §18）。

能力：
- 一个用户可配置多个 LLM（kind='llm'）与多个 Embedding（kind='embed'），使用时按 name / id 选择
- 每个 kind 下有且仅有一个默认项（is_default），由 set_default 保证唯一
- 供 model_service 做「请求参数 → 用户默认 → 系统种子」三级解析

主要函数：
- async def create_profile(session, user_id, ...) -> ModelProfile
- async def get_profile(session, profile_id, user_id) -> ModelProfile | None
- async def find_by_name(session, user_id, kind, name) -> ModelProfile | None
- async def list_profiles(session, user_id, kind=None, only_enabled=False) -> list[ModelProfile]
- async def get_default(session, user_id, kind) -> ModelProfile | None
- async def update_profile(session, profile, patch: dict) -> ModelProfile
- async def set_default(session, profile) -> None
- async def delete_profile(session, profile) -> None
- async def count_profiles(session, kind=None) -> int

关联方案：docs/design.md §18.1（数据模型）、§18.3（解析优先级）、§18.4（种子规则）。
"""
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelProfile


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
    """创建模型配置。若 is_default=True，自动清除同 kind 旧默认。"""
    if is_default:
        # 先把同 (user_id, kind) 的旧默认置 False
        await session.execute(
            update(ModelProfile)
            .where(
                ModelProfile.user_id == user_id,
                ModelProfile.kind == kind,
            )
            .values(is_default=False)
        )

    profile = ModelProfile(
        user_id=user_id,
        kind=kind,
        name=name,
        model=model,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        params_json=params_json,
        is_default=is_default,
        origin=origin,
    )
    session.add(profile)
    await session.commit()
    await session.refresh(profile)
    return profile


async def get_profile(
    session: AsyncSession, profile_id: int, user_id: str
) -> ModelProfile | None:
    """按 id + user_id 查单个配置。"""
    result = await session.execute(
        select(ModelProfile).where(
            ModelProfile.id == profile_id,
            ModelProfile.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def find_by_name(
    session: AsyncSession, user_id: str, kind: str, name: str
) -> ModelProfile | None:
    """按 (user_id, kind, name) 查配置（name 在用户内唯一）。"""
    result = await session.execute(
        select(ModelProfile).where(
            ModelProfile.user_id == user_id,
            ModelProfile.kind == kind,
            ModelProfile.name == name,
        )
    )
    return result.scalar_one_or_none()


async def list_profiles(
    session: AsyncSession,
    user_id: str,
    kind: str | None = None,
    only_enabled: bool = False,
) -> list[ModelProfile]:
    """列出当前用户的模型配置（可按 kind=llm|embed 过滤）。"""
    query = select(ModelProfile).where(ModelProfile.user_id == user_id)
    if kind:
        query = query.where(ModelProfile.kind == kind)
    if only_enabled:
        query = query.where(ModelProfile.enabled == True)  # noqa: E712
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_default(
    session: AsyncSession, user_id: str, kind: str
) -> ModelProfile | None:
    """获取当前用户的默认模型配置。"""
    query = select(ModelProfile).where(
        ModelProfile.user_id == user_id,
        ModelProfile.kind == kind,
        ModelProfile.is_default == True,  # noqa: E712
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def update_profile(
    session: AsyncSession, profile: ModelProfile, patch: dict
) -> ModelProfile:
    """局部更新配置；patch 中只含要改的字段。"""
    for key, value in patch.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    await session.commit()
    await session.refresh(profile)
    return profile


async def set_default(session: AsyncSession, profile: ModelProfile) -> None:
    """同一 (user_id, kind) 内：先把所有 is_default 置 False，再把目标置 True。"""
    await session.execute(
        update(ModelProfile)
        .where(
            ModelProfile.user_id == profile.user_id,
            ModelProfile.kind == profile.kind,
        )
        .values(is_default=False)
    )
    profile.is_default = True
    await session.commit()


async def delete_profile(session: AsyncSession, profile: ModelProfile) -> None:
    """删除配置。"""
    await session.delete(profile)
    await session.commit()


async def count_profiles(session: AsyncSession, kind: str | None = None) -> int:
    """统计配置数（判空，供种子注入使用）。"""
    query = select(func.count()).select_from(ModelProfile)
    if kind:
        query = query.where(ModelProfile.kind == kind)
    result = await session.execute(query)
    return result.scalar_one()
