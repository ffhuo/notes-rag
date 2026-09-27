"""数据访问·对话 — conversations / messages 表的 CRUD。

能力：
- 新建对话、追加消息（user / assistant 角色）
- 读取历史消息，支撑多轮问答的上下文拼接
- 与 chat_service 配合，保存来源/答案
- 会话列表（带派生标题与消息数），支撑问答页的「历史记录」

主要函数：
- new_conversation(session, user_id, vault_id) -> Conversation
- append_message(session, conv_id, user_id, role, content) -> Message
- get_history(session, conv_id) -> list[Message]
- get_conversation(session, conv_id, user_id) -> Conversation | None
- list_conversations(session, user_id, limit) -> list[dict]

关联方案：docs/design.md §4.3（Chat·历史）、§6（数据模型）。
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message

# 派生标题的长度上限（字符数，非字节）
_TITLE_LIMIT = 24


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


async def get_conversation(
    session: AsyncSession, conv_id: int, user_id: str = "default"
) -> Conversation | None:
    """按 id + user_id 取对话；不属于该用户时返回 None。

    **必须带 user_id**：conversations.id 是自增整数，可被枚举 —— 只按 id 取
    就能读到别人的会话（跨用户泄露）。
    """
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _derive_title(text: str | None) -> str:
    """首条提问 → 列表标题：压平空白后截断，超长加省略号。"""
    flat = " ".join((text or "").split())
    if not flat:
        return "新对话"
    return flat[:_TITLE_LIMIT] + ("…" if len(flat) > _TITLE_LIMIT else "")


async def list_conversations(
    session: AsyncSession,
    user_id: str = "default",
    limit: int = 50,
) -> list[dict]:
    """列出该用户的会话（最近在前），附派生标题与消息数。

    返回 [{id, title, message_count, created_at}]；created_at 是**朴素 UTC**
    datetime，格式化交给路由层（与 vaults 的毫秒时间戳出参同一套）。

    刻意用三条**批量**查询（会话 / 该批会话的 user 消息 / 该批会话的消息计数）
    而不是逐会话查标题 —— 后者是 N+1，会话一多就把连接池打满。
    计数只取 count(*) 不回表，避免把大段 assistant 正文拉进内存。
    """
    convs = list(
        (
            await session.execute(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.created_at.desc(), Conversation.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not convs:
        return []

    conv_ids = [c.id for c in convs]

    # 标题：按时间升序取「第一条 user 提问」；setdefault 保证不被后来的覆盖
    first_questions: dict[int, str] = {}
    rows = await session.execute(
        select(Message.conversation_id, Message.content)
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.role == "user",
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    for conv_id, content in rows.all():
        first_questions.setdefault(conv_id, content or "")

    count_rows = await session.execute(
        select(Message.conversation_id, func.count())
        .where(Message.conversation_id.in_(conv_ids))
        .group_by(Message.conversation_id)
    )
    counts: dict[int, int] = {conv_id: n for conv_id, n in count_rows.all()}

    return [
        {
            "id": c.id,
            "title": _derive_title(first_questions.get(c.id)),
            "message_count": int(counts.get(c.id, 0)),
            "created_at": c.created_at,
        }
        for c in convs
    ]
