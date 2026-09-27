"""路由·对话历史 — GET /api/v1/conversations 与 /conversations/{id}/messages。

能力：
- 列出当前用户的会话（标题 = 首条提问截断，附消息数与创建时间，最近在前）
- 读取某会话的消息（按时间升序），支撑问答页的「历史记录」视图

主要端点：
- GET /api/v1/conversations                  → list[ConversationOut]
- GET /api/v1/conversations/{id}/messages    → list[MessageOut]

鉴权：**只用 get_current_user_id**。不要再叠加 get_current_api_key
（该依赖只认 X-API-Key，而前端多用户登录态只发 Bearer JWT，叠加会让接口恒 401）。

越权与不存在一律返回 404：不区分「没有这个会话」和「不是你的会话」，
避免用返回码差异探测他人会话是否存在。会话存在但一条消息都没有时返回空数组（不是 404）。

关联方案：docs/design.md §4.3（Chat·历史）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_session
# 时间出参与 vaults 共用同一实现（13 位毫秒时间戳）；两份拷贝迟早会漂移
from app.api.routes.vaults import _epoch_ms
from app.models.schemas import ConversationOut, MessageOut
from app.repositories import conversation_repo

router = APIRouter(prefix="/api/v1", tags=["conversations"])


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    limit: int = Query(50, ge=1, le=200, description="最多返回多少条会话"),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """列出当前用户的会话（最近在前）。"""
    rows = await conversation_repo.list_conversations(session, user_id=user_id, limit=limit)
    return [
        ConversationOut(
            id=r["id"],
            title=r["title"],
            message_count=r["message_count"],
            created_at=_epoch_ms(r["created_at"]),
        )
        for r in rows
    ]


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conv_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """读取某会话的消息（按时间升序）；会话不存在或不属于当前用户 → 404。"""
    conv = await conversation_repo.get_conversation(session, conv_id, user_id=user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = await conversation_repo.get_history(session, conv_id)
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=_epoch_ms(m.created_at),
        )
        for m in messages
    ]