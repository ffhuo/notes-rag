"""ORM 模型 — SQLAlchemy 表定义（笔记元数据 / 对话历史）。

能力：
- 定义 notes / chunks / conversations / messages 四张表
- 通过 vector_id 与向量库（Chroma）关联同一份片段

主要类：
- Base: DeclarativeBase 基类
- Note: notes 表（file_path 唯一，记录标题 / 修改时间 / 索引时间）
- Chunk: chunks 表（note_id 外键，vector_id 唯一关联向量库）
- Conversation: conversations 表
- Message: messages 表（conversation_id 外键，role/content/时间）

关联方案：docs/design.md §6（数据模型）。
"""
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, ForeignKey, DateTime, func


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String)
    mtime: Mapped[float] = mapped_column(Float)
    indexed_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"))
    idx: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(String)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    vector_id: Mapped[str] = mapped_column(String, unique=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
