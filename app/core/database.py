"""数据库层 — SQLite（异步）引擎与会话管理。

能力：
- 用 SQLAlchemy 2.0 async + aiosqlite 创建异步引擎
- 提供 get_session 异步依赖，供 repository 层使用
- 提供 init_db 建表（create_all），或在 scripts/init_db.py 中调用

主要组件：
- create_database_engine(): 初始化引擎与会话工厂（lifespan 启动时调用）
- get_session(): FastAPI 依赖，yield 会话
- session_scope(): 独立会话上下文，供**请求作用域之外**的后台协程使用（作业层）
- init_db(): 依据 ORM 模型建表
- close_database_engine(): 释放引擎连接（lifespan 关闭时调用）

关联方案：docs/design.md §2（core/database.py）、§6（数据模型）。
"""
import os
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from app.core.config import settings
from app.models.orm import Base

_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


async def create_database_engine() -> AsyncEngine:
    """创建数据库引擎与会话工厂。

    依据 settings.sqlite_path 构建 sqlite+aiosqlite 连接，
    初始化全局 _engine 和 _async_session_factory。
    幂等：已初始化则直接返回。
    """
    global _engine, _async_session_factory

    if _engine is not None:
        return _engine

    # 确保数据目录存在
    db_path = settings.sqlite_path
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    _engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=settings.DEBUG,
    )
    _async_session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return _engine


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：yield 一个异步会话，请求结束自动关闭。"""
    if _async_session_factory is None:
        await create_database_engine()

    async with _async_session_factory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """独立会话上下文：供**请求作用域之外**的后台协程使用（作业层 run_service）。

    与 get_session（FastAPI 依赖）的区别：不绑定请求生命周期，由协程自己开/关。
    后台任务是长跑协程，跨阶段推进；若复用请求会话，会在请求结束的那一刻被关闭。
    默认 commit，异常 rollback（调用方无需自己管事务边界）。
    """
    if _async_session_factory is None:
        await create_database_engine()

    async with _async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """依据 ORM 模型建表（create_all）。"""
    if _engine is None:
        await create_database_engine()

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_database_engine() -> None:
    """释放数据库引擎连接池（lifespan 关闭时调用）。"""
    global _engine, _async_session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_factory = None
