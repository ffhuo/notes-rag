"""数据库层 — SQLite（异步）引擎与会话管理。

能力：
- 用 SQLAlchemy 2.0 async + aiosqlite 创建异步引擎
- 提供 get_session 异步依赖，供 repository 层使用
- 提供 init_db 建表（create_all），或在 scripts/init_db.py 中调用

主要组件：
- engine: create_async_engine(...)  # 异步引擎（sqlite+aiosqlite）
- AsyncSessionLocal: async_sessionmaker  # 会话工厂
- async def get_session() -> AsyncSession: FastAPI 依赖，yield 会话
- async def init_db() -> None: 依据 ORM 模型建表

关联方案：docs/design.md §2（core/database.py）、§6（数据模型）。
"""
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from app.core.config import Settings  # 或导入 settings 单例
from app.models.orm import Base  # 建表依据 ORM 定义


# engine = create_async_engine(f"sqlite+aiosqlite:///{settings.sqlite_path}")
# AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    ...


async def init_db() -> None:
    ...
