"""API·models — 多模型配置管理（多个 LLM / 多个 Embedding，使用时可选，见 §18）。

能力：
- 列出当前用户的模型配置（可按 kind=llm|embed|asr 过滤）
- 新增 / 修改 / 删除模型配置；删除被引用的 embedding 配置需先换模型重建索引
- 设置某 kind 的默认项（一个 kind 只有一个默认）
- 连通性测试：不落库直接试连（支持对未保存的配置试连）

主要端点：
- GET    /api/v1/models?kind=llm|embed|asr
- POST   /api/v1/models                  # { kind, name, model, provider?, base_url?, api_key?, params?, set_default? }
- POST   /api/v1/models/test             # 试连未保存的配置（body 同 create，不含 set_default）
- GET    /api/v1/models/{id}
- PATCH  /api/v1/models/{id}
- DELETE /api/v1/models/{id}
- POST   /api/v1/models/{id}/default     # 设为该 kind 的默认项
- POST   /api/v1/models/{id}/test        # 试连已保存的配置

安全约定：
- 出参**永不返回 api_key**，仅给 api_key_masked（如 sk-ab****yz），见 §18.6
- base_url / api_key 允许留空：base_url 空 = OpenAI 官方端点，api_key 空 = 不带鉴权

分层约定：本文件只做「入参校验 + 调 service + 把领域异常翻译成 HTTP 状态码」，
DB 读写一律经 model_repo / model_service，不在路由里写 SQL。

关联方案：docs/design.md §8（配置总览）、§10 模块索引 M08（多模型管理）。
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.database import get_session
from app.models import ModelProfile
from app.models.schemas import (
    ModelProfileCreate,
    ModelProfileOut,
    ModelProfileUpdate,
    ModelRuntime,
    ModelTestResult,
)
from app.repositories import model_repo, vault_repo
from app.services import model_service
from app.services.model_service import to_out, to_runtime

router = APIRouter(prefix="/api/v1/models", tags=["models"])

# kind 白名单：llm（对话）/ embed（向量化）/ asr（语音识别）。
# 三者在同一个 model_profiles 表里靠 kind 区分，各自有独立的默认项；
# 加 asr 不需要迁移（DB 列是普通字符串），但要同步 test_connection 的分支。
_KINDS = ("llm", "embed", "asr")


def _require_kind(kind: str) -> str:
    """kind 只允许 llm / embed / asr。"""
    if kind not in _KINDS:
        raise HTTPException(
            status_code=422, detail=f"kind 必须是 {' | '.join(_KINDS)} 之一，收到 {kind!r}"
        )
    return kind


async def _get_or_404(session: AsyncSession, model_id: int, user_id: str) -> ModelProfile:
    """按 id + 归属取配置，取不到直接 404。"""
    profile = await model_repo.get_profile(session, model_id, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"模型配置不存在：id={model_id}")
    return profile


def _runtime_from_payload(payload: ModelProfileCreate, user_id: str) -> ModelRuntime:
    """把**未落库**的配置转成 ModelRuntime，用于试连。

    构造一个临时 ORM 实例（不加入 session、不 commit），只为复用 to_runtime
    这一份唯一规则，避免在路由里重写一遍。
    """
    transient = ModelProfile(
        user_id=user_id,
        kind=payload.kind,
        name=payload.name,
        model=payload.model,
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=payload.api_key,
        params_json=json.dumps(payload.params or {}),
    )
    return to_runtime(transient)


@router.get("", response_model=list[ModelProfileOut])
async def list_models(
    kind: str | None = Query(default=None, pattern="^(llm|embed|asr)$"),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """列出当前用户的模型配置（可按 kind=llm|embed|asr 过滤）。"""
    return await model_service.list_models(session, user_id, kind)


@router.post("", response_model=ModelProfileOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelProfileCreate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """新增模型配置（同名同 kind 已存在 → 409；set_default=true 时同时设为默认）。"""
    _require_kind(payload.kind)

    existing = await model_repo.find_by_name(session, user_id, payload.kind, payload.name)
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"同 kind 下已存在同名配置：{payload.name!r}"
        )

    return await model_service.create_model(session, user_id, payload)


@router.post("/test", response_model=ModelTestResult)
async def test_unsaved_model(
    payload: ModelProfileCreate,
    user_id: str = Depends(get_current_user_id),
):
    """试连**未保存**的配置：不落库，直接按入参发起一次真实调用。"""
    _require_kind(payload.kind)
    runtime = _runtime_from_payload(payload, user_id)
    return await model_service.test_connection(runtime)


@router.get("/{model_id}", response_model=ModelProfileOut)
async def get_model(
    model_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """取单个配置（api_key 已脱敏）。"""
    profile = await _get_or_404(session, model_id, user_id)
    return to_out(profile)


@router.patch("/{model_id}", response_model=ModelProfileOut)
async def update_model(
    model_id: int,
    payload: ModelProfileUpdate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """局部更新配置。

    改 embedding 的 model/params 不会自动重建索引 —— 该配置已建过索引的 vault
    需要各自 reindex，否则新旧向量混在同一 collection。由前端提示用户决定。
    """
    profile = await _get_or_404(session, model_id, user_id)

    # 改名需保持 (user_id, kind, name) 唯一
    if payload.name is not None and payload.name != profile.name:
        clash = await model_repo.find_by_name(session, user_id, profile.kind, payload.name)
        if clash is not None and clash.id != profile.id:
            raise HTTPException(
                status_code=409, detail=f"同 kind 下已存在同名配置：{payload.name!r}"
            )

    return await model_service.update_model(session, profile, payload)


@router.delete("/{model_id}")
async def delete_model(
    model_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """删除配置。

    embedding 配置若仍被某个 vault 引用（当前启用项或已建索引列表）→ 409，
    提示先对该 vault 换 embedding 并重建索引；直接删会让该 vault 无法检索。
    """
    profile = await _get_or_404(session, model_id, user_id)

    if profile.kind == "embed":
        for vault in await vault_repo.list_vaults(session, user_id):
            indexed = _indexed_profiles(vault)
            if vault.embed_profile_id == profile.id or profile.id in indexed:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"embedding 配置仍被 vault(id={vault.id}, name={vault.name!r}) 引用，"
                        f"请先为其换 embedding 并重建索引"
                    ),
                )

    await model_service.delete_model(session, profile)
    return {"deleted": True, "id": model_id}


@router.post("/{model_id}/default", response_model=ModelProfileOut)
async def set_default_model(
    model_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """把该配置设为所属 kind 的默认项（同 kind 旧默认自动取消）。"""
    profile = await _get_or_404(session, model_id, user_id)
    return await model_service.set_default(session, profile)


@router.post("/{model_id}/test", response_model=ModelTestResult)
async def test_model(
    model_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """试连已保存的配置：embed 试嵌一条短文本，llm 试一次极短对话。"""
    profile = await _get_or_404(session, model_id, user_id)
    runtime = to_runtime(profile)
    return await model_service.test_connection(runtime)


def _indexed_profiles(vault) -> list[int]:
    """vault.embed_indexed_profiles（JSON 字符串）→ int 列表；非法值按空处理。"""
    try:
        raw = json.loads(vault.embed_indexed_profiles or "[]")
    except (ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, int)]