"""数据访问·对话 — conversations / messages 表的 CRUD。

能力：
- 新建对话、追加消息（user / assistant 角色）
- 读取历史消息，支撑多轮问答的上下文拼接
- 与 chat_service 配合，保存来源/答案

主要函数：
- new_conversation(session) -> Conversation: 新建对话并返回
- append_message(session, conv_id, role, content) -> None: 追加一条消息
- get_history(session, conv_id) -> list[Message]: 取某对话的历史

关联方案：docs/design.md §4.3（Chat·历史）、§6（数据模型）。
"""
from sqlalchemy.ext.asyncio import AsyncSession


async def new_conversation(session: AsyncSession):
    ...


async def append_message(session: AsyncSession, conv_id: int, role: str, content: str) -> None:
    ...


async def get_history(session: AsyncSession, conv_id: int) -> list:
    ...
