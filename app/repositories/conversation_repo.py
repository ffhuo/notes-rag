"""数据访问·对话 — conversations / messages 表的 CRUD。

能力：
- 新建对话、追加消息（user / assistant 角色）
- 读取历史消息，支撑多轮问答的上下文拼接
- 与 chat_service 配合，保存来源/答案

主要函数：
- new_conversation(session, user_id, vault_id) -> Conversation
- append_message(session, conv_id, user_id, role, content) -> Message
- get_history(session, conv_id) -> list[Message]

关联方案：docs/design.md §4.3（Chat·历史）、§6（数据模型）。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message


async def new_conversation(
    session: AsyncSession,
    user_id: str = "default",
    vault_id: int | None = None,
) -> Conversation:
    """新建对话并返回。"""
    conv = Conversation(user_id=user_id, vault_id=vault_id)
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv


async def append_message(
    session: AsyncSession,
    conv_id: int,
    role: str,
    content: str,
    user_id: str = "default",
) -> Message:
    """追加一条消息。"""
    msg = Message(
        conversation_id=conv_id,
        user_id=user_id,
        role=role,
        content=content,
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


async def get_history(session: AsyncSession, conv_id: int) -> list[Message]:
    """取某对话的历史消息，按时间升序。"""
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())
