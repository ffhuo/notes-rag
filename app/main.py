"""应用入口 — FastAPI 实例与启动装配。

能力：
- 创建 FastAPI app，挂载各路由（ingest / search / chat / health）
- 配置 CORS 中间件（依据 Settings.cors_origins）
- 生命周期：启动时建表（init_db）、加载向量库；关闭时释放
- 注册异常处理器（401 鉴权失败 / 500 内部错误）
- 自动提供 /docs 交互式文档

主要装配：
- app = FastAPI(title="rag-as-api")
- include_router(ingest/search/chat/health)
- add_middleware(CORSMiddleware)
- lifespan / @app.on_event("startup")：调用 init_db()
- 异常处理器：401 / 500

关联方案：docs/design.md §1（架构总览）、§2（main.py）、§9（Phase 0 脚手架）。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from loguru import logger
from app.core.config import settings

from app.api.routes import ingest, search, chat, health
from app.core.config import Settings  # 或 settings

# TODO: 以下装配按 design.md §9 逐步实现
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=settings.cors_origins.split(","),
#     allow_methods=["*"], allow_headers=["*"],
# )
# app.include_router(ingest.router)
# app.include_router(search.router)
# app.include_router(chat.router)
# app.include_router(health.router)
#
# @app.on_event("startup")
# async def on_startup():
#     await init_db()

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理函数。

    在应用启动时初始化数据库引擎，关闭时释放资源。
    """
    logger.info("Starting application")
    # await init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down application")
    # await close_database_engine()
    logger.info("Database engine closed")


def run_app():
    """运行 FastAPI 应用。

    启动 FastAPI 应用，监听指定端口。
    """
    app = FastAPI(
        title="rag-as-api",
        version=settings.version,
        description="""
            RAG API for document retrieval and generation.
        """,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.run(host=settings.host, port=settings.port)

def init_logger():
    """初始化应用日志记录器。

    配置常规日志文件与错误日志文件的输出参数，
    包括日志轮转、保留时长、记录级别等设置。
    """
    logger.add(
        settings.log_file,
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        level=settings.log_level,
    )

    logger.add(settings.log_error_file, backtrace=True, diagnose=True, level="ERROR")


if __name__ == "__main__":
    init_logger()
