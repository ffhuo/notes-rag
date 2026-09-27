"""API·依赖注入 — 向路由提供 config / db session / 鉴权 / RAG 组件。

能力：
- 注入配置（get_settings）
- 注入数据库会话（get_session，复用 core.database）
- 注入 API Key / 当前用户（复用 core.security）
- 构造向量库实例（get_vector_store）
- 解析「检索用 embedding 运行时」（resolve_embed_runtime）—— 供 search / chat 共用

主要函数：
- get_settings() -> Settings
- get_vector_store(collection_name=None) -> VectorStore
- resolve_embed_runtime(session, settings, user_id, vault)
      -> tuple[ModelRuntime, int]：按 vault 已建索引的模型解析，含跨模型兼容守卫

关联方案：docs/design.md §1（依赖原则）、§2（api/deps.py）、§18.2（embedding 与 vault 绑定）。
"""
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.database import get_session
from app.core.security import get_current_api_key, get_current_user
from app.models import Vault
from app.models.schemas import ModelRuntime
from app.rag.vectorstore import VectorStore
from app.services import model_service
from app.services.model_service import (
    EmbedModelMismatch,
    ModelNotConfigured,
    ModelNotFound,
    to_runtime,
)

# 当前用户依赖：供 vault/auth 路由注入，返回 user_id（单用户为 "default"）
get_current_user_id = get_current_user

# 显式声明对外导出：get_session / get_current_api_key 由本模块转出供路由引用
__all__ = [
    "get_settings",
    "get_session",
    "get_current_api_key",
    "get_current_user_id",
    "get_vector_store",
    "resolve_embed_runtime",
]


def get_settings() -> Settings:
    """注入配置单例。"""
    return settings


def get_vector_store(collection_name: str | None = None) -> VectorStore:
    """构造向量库实例。

    **不缓存单例**：向量集合按 (vault_id, embed_profile_id) 命名隔离（§18.2），
    一个全局单例只能指向单一集合，故这里只做「按需构造」。
    collection_name 留空时落到 VectorStore 的默认集合。
    """
    if collection_name is None:
        return VectorStore(persist_dir=settings.chroma_dir)
    return VectorStore(persist_dir=settings.chroma_dir, collection_name=collection_name)


async def resolve_embed_runtime(
    session: AsyncSession,
    settings: Settings,
    user_id: str,
    vault: Vault | None = None,
) -> "tuple[ModelRuntime, int]":
    """解析检索 / 问答要用的 embedding 运行时。

    解析链：vault.embed_profile_id → 用户默认 embed profile（§18.3）。
    **embedding 不由请求指定**（§18.2）—— 换模型必须重新建索引，否则同一 collection
    会混入两种向量空间，检索结果失去意义。

    提供 vault 时追加两道前置条件检查：
    - 该 vault 从未建过索引（indexed_at 为空）→ 409，提示先提交 sync 作业
      （否则检索只会静默返回空，用户以为「没有相关内容」，实际是根本没索引）
    - 该 vault 未用此 embedding 模型建过索引 → 409，提示先 reindex

    vault 为 None（不限定 vault）时跳过「已建索引」与兼容性检查，但仍要解析 embedding ——
    检索链路必须先嵌查询向量，没有运行时就只能报错，故缺配置时同样 409。

    Returns:
        (runtime, profile_id)
    """
    if vault is not None and vault.indexed_at is None:
        raise HTTPException(
            status_code=409,
            detail=f"vault(id={vault.id}) 尚未建索引，请先提交一次 sync 作业再检索",
        )

    ref = str(vault.embed_profile_id) if (vault is not None and vault.embed_profile_id) else None

    try:
        profile = await model_service.resolve_profile(
            session, settings, "embed", ref=ref, user_id=user_id
        )
    except ModelNotConfigured:
        raise HTTPException(
            status_code=409,
            detail="尚未配置向量模型：请到「模型」页新增一个 kind=embed 的配置",
        )
    except ModelNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))

    if vault is not None:
        try:
            model_service.assert_embed_compatible(vault, profile)
        except EmbedModelMismatch as e:
            raise HTTPException(status_code=409, detail=str(e))

    return to_runtime(profile), profile.id