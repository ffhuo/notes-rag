"""数据库层 — SQLite（异步）引擎与会话管理。

能力：
- 用 SQLAlchemy 2.0 async + aiosqlite 创建异步引擎
- 提供 get_session 异步依赖，供 repository 层使用
- 提供 init_db 建表（create_all），或在 scripts/init_db.py 中调用

主要组件：
- create_database_engine(): 初始化引擎与会话工厂（lifespan 启动时调用）
- get_session(): FastAPI 依赖，yield 会话
- session_scope(): 独立会话上下文，供**请求作用域之外**的后台协程使用（作业层）
- init_db(): 依据 ORM 模型建表，并补齐已存在表的增量列（本项目无迁移框架）
- close_database_engine(): 释放引擎连接（lifespan 关闭时调用）

关联方案：docs/design.md §2（core/database.py）、§6（数据模型）。
"""
import os
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from app.core.config import settings
from app.models import Base

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

    # WAL 模式 + busy_timeout（M03 §5.13.8 红线之一）：
    # 后台作业高频写进度与 API 同时读写并存，默认 journal 模式下读写互斥，
    # 会出现 API 读被作业写锁阻塞（database is locked）。WAL 读写不互斥，
    # busy_timeout 兜底偶发的锁竞争。WAL 是库级持久设置，每个新连接都声明一次。
    @event.listens_for(_engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

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
    """依据 ORM 模型建表（create_all），并补齐已存在表的增量列。"""
    if _engine is None:
        await create_database_engine()

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_image_cache_columns(conn)


# image_cache 的增量列：create_all **不会**给已存在的表加列，而本项目没有迁移框架
# （无 Alembic）。这里按需 ALTER 补齐 —— 只列真正需要的列，不造通用迁移机制。
# uid 的 DDL 刻意不给默认值：存量行只能落 NULL，而 SQLite 的 UNIQUE 索引允许多个
# NULL，不会因「多行都是 ''」而建索引失败；新行由代码保证写入非空 uid。
_IMAGE_CACHE_NEW_COLUMNS: dict[str, str] = {
    "uid": "VARCHAR",
    "source_ref": "VARCHAR DEFAULT ''",
}


async def _ensure_image_cache_columns(conn) -> None:
    """补齐 image_cache 的增量列与 uid 唯一索引（幂等，可重复执行）。"""
    result = await conn.exec_driver_sql("PRAGMA table_info(image_cache)")
    cols = {row[1] for row in result.fetchall()}
    if not cols:            # 表尚不存在：create_all 已按新模型建出，无需补列
        return
    for name, ddl in _IMAGE_CACHE_NEW_COLUMNS.items():
        if name not in cols:
            # 列名与 DDL 均来自本模块常量，无外部输入
            await conn.exec_driver_sql(f"ALTER TABLE image_cache ADD COLUMN {name} {ddl}")
    # 与模型里 Index("uq_image_cache_uid", unique=True) 同名，故可幂等重复执行
    await conn.exec_driver_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_image_cache_uid ON image_cache(uid)"
    )


async def close_database_engine() -> None:
    """释放数据库引擎连接池（lifespan 关闭时调用）。"""
    global _engine, _async_session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_factory = None
