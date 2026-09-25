"""API·models — 多模型配置管理（多个 LLM / 多个 Embedding，使用时可选，见 §18）。

能力：
- 列出当前用户的模型配置（可按 kind=llm|embed 过滤）
- 新增 / 修改 / 删除模型配置；删除被引用的 embedding 配置需先换模型重建索引
- 设置某 kind 的默认项（一个 kind 只有一个默认）
- 连通性测试：不落库直接试连（支持对未保存的配置试连）

主要端点：
- GET    /api/v1/models?kind=llm|embed
- POST   /api/v1/models                  # { kind, name, model, provider?, base_url?, api_key?, params?, set_default? }
- POST   /api/v1/models/test             # 试连未保存的配置（body 同 create，不含 set_default）
- GET    /api/v1/models/{id}
- PATCH  /api/v1/models/{id}
- DELETE /api/v1/models/{id}
- POST   /api/v1/models/{id}/default     # 设为该 kind 的默认项
- POST   /api/v1/models/{id}/test        # 试连已保存的配置

安全约定：
- 出参**永不返回 api_key**，仅给 api_key_masked（如 sk-ab****yz），见 §18.6
- base_url / api_key 允许留空，表示回退 .env 的 LLM_* / EMBED_*（§18.3 回退规则）

关联方案：docs/design.md §18（多模型管理）、§8（配置与安全）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_settings
from app.core.database import get_session
from app.models.schemas import (
    ModelProfileCreate,
    ModelProfileOut,
    ModelProfileUpdate,
    ModelTestResult,
)
from app.services import model_service

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get("", response_model=list[ModelProfileOut])
async def list_models(
    kind: str | None = Query(default=None, pattern="^(llm|embed)$"),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """列出当前用户的模型配置（可按 kind=llm|embed 过滤）。"""
    return model_service.list_models(user_id, kind)


@router.post("", response_model=ModelProfileOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelProfileCreate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
):
    # 同名同 kind 已存在 → 409；set_default=true → 调用 model_service.set_default
    ...


@router.post("/test", response_model=ModelTestResult)
async def test_unsaved_model(
    payload: ModelProfileCreate,
    user_id: str = Depends(get_current_user_id),
    settings=Depends(get_settings),
):
    # 不落库：把 payload 转成 ModelRuntime（应用 .env 回退）后直接试连
    ...


@router.get("/{model_id}", response_model=ModelProfileOut)
async def get_model(
    model_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    ...


@router.patch("/{model_id}", response_model=ModelProfileOut)
async def update_model(
    model_id: int,
    payload: ModelProfileUpdate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # 若改的是 embedding 且该配置已建过索引 → 提示需对该 vault 重新索引（由前端决定）
    ...


@router.delete("/{model_id}")
async def delete_model(
    model_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # 被 vault.embed_profile_id 引用 → 409 并提示先换 embedding 重建索引
    ...


@router.post("/{model_id}/default", response_model=ModelProfileOut)
async def set_default_model(
    model_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    ...


@router.post("/{model_id}/test", response_model=ModelTestResult)
async def test_model(
    model_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings=Depends(get_settings),
):
    # embed：嵌入一条短文本返回维度；llm：极小 max_tokens 试一次返回首块内容
    ...
