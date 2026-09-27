"""路由·问答 — POST /api/v1/chat（SSE 流式）。

能力：
- 接收 query / conversation_id / top_k / vault_id / llm_profile
- 以 text/event-stream 流式返回：token 片段 / sources 来源 / done 结束 / error 错误
- 受鉴权保护（get_current_user：X-API-Key 或 Bearer JWT，见 §17.3）
- 用 StreamingResponse 包装 chat_service.stream 的生成器
- **本次用哪个 LLM**：req.llm_profile（name 或 id）→ 用户默认（见 §18.3）；无 llm 配置则 409

主要端点：
- POST /api/v1/chat → 解析 llm_runtime 后调 chat_service.stream，包装为 SSE

关联方案：docs/design.md §4.3（Chat 时序）、§5（API 设计）、§18（多模型管理）。
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user_id,
    get_session,
    get_settings,
    resolve_embed_runtime,
)
from app.core.config import Settings
from app.models.schemas import ChatRequest
from app.repositories import vault_repo
from app.services import chat_service, model_service
from app.services.model_service import (
    ModelNotConfigured,
    ModelNotFound,
    to_runtime,
)

router = APIRouter(prefix="/api/v1", tags=["chat"])

# SSE 响应头：禁用缓冲，避免反向代理把 token 攒到最后一次性下发
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event: str, data) -> str:
    """按 SSE 规范编码单个事件：event 行 + data 行 + 空行分隔。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _resolve_llm(
    session: AsyncSession, settings: Settings, user_id: str, ref: str | None
) -> "object":
    """解析本次问答用哪个 LLM：ref（name 或 id）→ 该 kind 的默认项。

    LLM 无状态耦合，可逐请求自由切换（§18.2），故不做类似 embedding 的兼容守卫。
    """
    try:
        profile = await model_service.resolve_profile(
            session, settings, "llm", ref=ref, user_id=user_id
        )
    except ModelNotConfigured:
        raise HTTPException(
            status_code=409,
            detail="尚未配置 LLM：请到「模型」页新增一个 kind=llm 的配置",
        )
    except ModelNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    return to_runtime(profile)


@router.post("/chat")
async def chat(
    req: ChatRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """检索增强问答（SSE）。

    错误策略：参数 / 配置类错误在**建流之前**直接返回 4xx（前端拿状态码即可）；
    生成过程中的异常（LLM 超时等）已在流内，转成 error 事件下发。

    鉴权只用 get_current_user（同时接受 X-API-Key 与 Bearer JWT）；
    叠加 get_current_api_key（只认 X-API-Key）会让多用户登录态必然 401。
    """
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=422, detail="query 不能为空")

    conversation_id: int | None = None
    if req.conversation_id:
        try:
            conversation_id = int(req.conversation_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="conversation_id 必须是整数")

    # vault 可选：给了就必须归属正确，并据此确定检索用 embedding
    vault = None
    if req.vault_id:
        try:
            vault_id = int(req.vault_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="vault_id 必须是整数 id")
        vault = await vault_repo.get_vault(session, vault_id, user_id)
        if vault is None:
            raise HTTPException(
                status_code=404, detail=f"vault_id={vault_id} 不存在或不属于当前用户"
            )

    llm_runtime = await _resolve_llm(session, settings, user_id, req.llm_profile)
    embed_runtime, embed_profile_id = await resolve_embed_runtime(
        session, settings, user_id, vault
    )

    async def event_stream():
        """把 chat_service 的事件 dict 逐个编码为 SSE。"""
        try:
            async for event in chat_service.stream(
                req.query,
                session=session,
                user_id=user_id,
                conversation_id=conversation_id,
                top_k=req.top_k,
                vault_id=vault.id if vault is not None else None,
                embed_runtime=embed_runtime,
                embed_profile_id=embed_profile_id,
                llm_runtime=llm_runtime,
            ):
                yield _sse(event.get("type", "message"), event.get("data"))
        except Exception as e:  # noqa: BLE001 —— 流内异常转 error 事件，不能裸抛断流
            logger.exception("chat 流中断")
            yield _sse("error", str(e))

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
    )