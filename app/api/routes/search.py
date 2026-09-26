"""路由·检索 — POST /api/v1/search。

能力：
- 接收 query / top_k / threshold / vault_id，返回语义检索命中
- 受 API Key 保护（依赖 get_current_api_key）
- **embedding 不由请求指定**：必须沿用该 vault 建索引时的模型，故接口不暴露 embed_profile（§18.2）；
  由 model_service 按 vault.embed_profile_id 解析并做 assert_embed_compatible 守卫

主要端点：
- POST /api/v1/search → 解析 embed_runtime 后调 retrieval_service.retrieve

关联方案：docs/design.md §4.2（Search 时序）、§5（API 设计）、§18（多模型管理）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_api_key,
    get_current_user_id,
    get_session,
    get_settings,
    resolve_embed_runtime,
)
from app.core.config import Settings
from app.models.schemas import SearchRequest, SearchResponse
from app.repositories import vault_repo
from app.services import retrieval_service

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    _: str = Depends(get_current_api_key),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SearchResponse:
    """语义检索：query → 向量 → Top-K → 命中列表。

    检索必须绑定 vault：向量集合按 (vault_id, embedding 模型) 隔离，
    脱离 vault 无法确定查哪个集合、用哪个 embedding。
    """
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=422, detail="query 不能为空")

    if req.vault_id is None or req.vault_id == "":
        raise HTTPException(status_code=422, detail="vault_id 必填：检索必须绑定一个 vault")
    try:
        vault_id = int(req.vault_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="vault_id 必须是整数 id")

    # 归属校验：vault 必须属于当前用户（repo 强制带 user_id）
    vault = await vault_repo.get_vault(session, vault_id, user_id)
    if vault is None:
        raise HTTPException(
            status_code=404, detail=f"vault_id={vault_id} 不存在或不属于当前用户"
        )

    # embedding 跟随该 vault 已建索引的模型；未建索引 → 409（守卫在 deps 内）
    embed_runtime, embed_profile_id = await resolve_embed_runtime(
        session, settings, user_id, vault
    )

    hits = await retrieval_service.retrieve(
        req.query,
        top_k=req.top_k,
        threshold=req.threshold,
        vault_id=vault.id,
        embed_profile_id=embed_profile_id,
        embed_runtime=embed_runtime,
    )
    return SearchResponse(hits=hits)