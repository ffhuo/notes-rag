"""应用入口 — FastAPI 实例与启动装配。

能力：
- 创建 FastAPI app，挂载各路由（ingest / search / chat / health / vaults / auth / models）
- 配置 CORS 中间件（依据 Settings.cors_origins）
- 生命周期：启动时建表（init_db）、加载向量库、**种子注入默认模型配置**（§18.4）；关闭时释放
- 注册异常处理器（401 鉴权失败 / 500 内部错误）
- 自动提供 /docs 交互式文档

主要装配：
- app = FastAPI(title="notes-rag")
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
from app.core.middleware import LoggingMiddleware

from app.api.routes import ingest, search, chat, health, vaults, auth, models
from app.core.config import Settings  # 或 settings

# TODO: 以下装配按 docs/design.md §9 逐步实现
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=settings.cors_origins.split(","),
#     allow_methods=["*"], allow_headers=["*"],
# )
# app.include_router(ingest.router)
# app.include_router(search.router)
# app.include_router(chat.router)
# app.include_router(health.router)
# app.include_router(vaults.router)     # §17.2 vault 前端管理
# app.include_router(auth.router)       # §17.3 多用户 JWT（ENABLE_MULTIUSER=true 时）
# app.include_router(models.router)     # §18 多模型管理
#
# @app.on_event("startup")
# async def on_startup():
#     await init_db()
#     # 种子注入：model_profiles 表为空时用 .env 构造默认 LLM / Embedding 配置（§18.4）
#     # await model_service.seed_from_env(session, settings)

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理函数。

    在应用启动时初始化数据库引擎，关闭时释放资源。
    """

    try:
        logger.info("Starting application")
        # await init_db()
        logger.info("Database initialized")
        yield
    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise
    finally:
        logger.info("Shutting down application")

        try:
            logger.info("Shutting down application")
            # await close_database_engine()
            logger.info("Database engine closed")
        except Exception as e:
            logger.error("Error during shutdown", error=str(e))
            raise

        logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """创建 FastAPI 应用。

    创建并配置 FastAPI 应用实例，包括中间件、路由和异常处理。
    """
    app = FastAPI(
        title="notes-rag",
        version=settings.version,
        description="""
            RAG API for document retrieval and generation.
        """,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
        swagger_ui_params={
            "persistAuthorization": True,
            "displayRequestDuration": True,
            "filter": True,
            "tryItOutEnabled": True,
        },
    )

    cors_origins: list[str] = settings.get_cors_origins()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"], allow_headers=["*"],
        )
    
    app.add_middleware(LoggingMiddleware)

    # app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "message": "RAG API",
            "version": app.version,
            "docs_url": "/docs" if settings.DEBUG else None,
        }
    
    return app
    

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


app: FastAPI = create_app()

if __name__ == "__main__":
    import uvicorn

    init_logger()

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.DEBUG,
        log_level=settings.log_level.lower(),
        access_log=settings.DEBUG,
    )
    