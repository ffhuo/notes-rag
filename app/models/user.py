"""ORM·用户 — users 表（多用户模式，ENABLE_MULTIUSER=true 时启用）。"""
import uuid

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, DateTime, func

from app.models.base import Base


class User(Base):
    """用户表。

    uid: 对外唯一标识（UUID hex 字符串），JWT sub 和所有 user_id 外键均用它。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String, unique=True, default=lambda: uuid.uuid4().hex)
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
