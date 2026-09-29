"""应用入口 — FastAPI 实例与启动装配。

能力：
- 创建 FastAPI app，挂载各路由（ingest / search / chat / health / vaults / auth / models）
- 配置 CORS 中间件（依据 Settings.cors_origins）与请求日志中间件
- 生命周期：启动时建表（init_db）+ **清理残留作业** + 可选启动定时同步；
  关闭时取消后台任务并释放引擎（close_database_engine）
- 自动提供 /docs 交互式文档

启动清理为什么必须做（M03 §5.13.6）：
`asyncio.create_task` 派发的作业随进程重启消失，但 DB 里还留着 `running` 行。
不清理的话用户会看到一条永远 running 的僵尸作业，且「该 vault 是否已有作业在跑」的判断
被永久阻塞（新提交一律 409）。策略是**一律标 aborted，不做断点续跑** ——
sync 本身幂等，重跑一次比持久化中间态简单得多，也更不容易留下半残状态。

关联方案：docs/design.md §2（架构总览）、§3（目录结构与职责）；
         M03 §5.13（作业化执行）、M01（应用装配）。
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.router import router as api_router
from app.core.config import settings
from app.core.database import close_database_engine, init_db, session_scope
from app.core.middleware import LoggingMiddleware
from app.mcp.server import build_http_app, mcp as mcp_server
from app.services import run_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期：建表 → 清理残留作业 → 可选定时同步；关闭时取消任务并释放引擎。"""
    background_tasks: list[asyncio.Task] = []
    try:
        logger.info("Starting application")
        await init_db()
        logger.info("Database initialized")

        # 启动清理：残留 queued / running 作业 → aborted（僵尸作业会永久阻塞新提交）
        async with session_scope() as session:
            stale = await run_service.recover_stale(session)
        if stale:
            logger.warning(
                "标记 {} 条残留作业为 aborted（进程上次未正常退出；如需收敛请手动跑一次 sync）",
                stale,
            )

        # 定时同步：INGEST_SYNC_INTERVAL > 0 时启用；对全部 vault 依次提交增量作业
        if settings.ingest_sync_interval > 0:
            background_tasks.append(
                asyncio.create_task(
                    run_service.run_scheduled_sync(settings.ingest_sync_interval),
                    name="scheduled-sync",
                )
            )
            logger.info("定时同步已启用：每 {} 秒", settings.ingest_sync_interval)

        # 启动补一次同步：INGEST_SYNC_ON_STARTUP=true 时（即上面那次「手动跑一次」的自动化版本）
        # 实现建议：在 run_service 里加 submit_all(trigger="startup")，抢不到锁的 vault 静默跳过。
        # 注意别在 lifespan 里直接 await 它 —— 那会把启动阻塞到全量索引完成。

        # MCP Streamable HTTP 的会话管理器：Starlette 的 Mount **不会**自动运行子应用的
        # lifespan，必须在父应用 lifespan 内手动启动，否则 /mcp 请求会因会话管理器未就绪而失败。
        async with mcp_server.session_manager.run():
            yield
    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise
    finally:
        logger.info("Shutting down application")
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        try:
            await close_database_engine()
            logger.info("Database engine closed")
        except Exception as e:
            logger.error("Error during shutdown", error=str(e))
        logger.info("Application shutdown complete")



def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用：中间件、路由、异常处理。"""
    app = FastAPI(
        title="notes-rag",
        version=settings.version,
        description="RAG API for document retrieval and generation.",
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

    # 中间件（注册顺序与执行顺序相反：后注册的先执行）
    cors_origins = settings.get_cors_origins()
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(LoggingMiddleware)

    # 路由（统一从 app/api/router.py 聚合引用）
    app.include_router(api_router)

    # ===== MCP（远程 HTTP 接入）：挂到 /mcp，供 agent 直连 =====
    # 必须在下方 SPA 兜底路由**之前**注册，否则 GET /mcp 会被兜底吞掉返回 index.html。
    # 鉴权由工具内部按请求头解析用户级 API Key 完成（见 app/mcp/auth.py）。
    app.mount("/mcp", build_http_app())

    # ===== 前端静态托管（单镜像部署：SPA 与 API 同源，免 CORS）=====
    # 产物由 frontend/ 的 vite build 输出到 app/static（见 frontend/vite.config.js）。
    # 未构建 / UI_ENABLED=false 时退化为纯 API：根路径返回服务信息 JSON。
    static_dir = Path(__file__).parent / "static"
    index_file = static_dir / "index.html"
    ui_ready = settings.ui_enabled and index_file.is_file()
    if settings.ui_enabled and not ui_ready:
        logger.warning("UI_ENABLED=true 但未找到前端产物 {}，本次仅提供 API", index_file)

    # 根路由
    @app.get("/", include_in_schema=False)
    async def root():
        if ui_ready:
            return FileResponse(index_file)
        return {
            "message": "RAG API",
            "version": app.version,
            "docs_url": "/docs" if settings.DEBUG else None,
        }

    if ui_ready:
        # 构建产物除 index.html 外统一位于 /assets 下
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            """SPA 兜底：未命中的前端子路由返回 index.html；API 未命中仍返回 404。"""
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            # 根级静态文件（favicon 等）：仅放行目录内真实文件，防路径穿越
            candidate = (static_dir / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
                return FileResponse(candidate)
            return FileResponse(index_file)

    # 401 鉴权失败统一格式
    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc):
        return JSONResponse(
            status_code=401,
            content={"detail": "无效或缺失的鉴权凭据"},
            headers={"WWW-Authenticate": "ApiKey, Bearer"},
        )

    return app


def init_logger():
    """初始化日志文件 sink：常规日志 + 错误日志。"""
    logger.add(
        settings.log_file,
        rotation=settings.log_rotation,
        retention=settings.log_retention,
        level=settings.log_level,
    )
    logger.add(settings.log_error_file, backtrace=True, diagnose=True, level="ERROR")


# 模块级初始化日志：必须在 create_app 之前执行，确保 uvicorn 以 import 方式
# 加载本模块（如 `uvicorn app.main:app`）时文件 sink 也能生效。
init_logger()

app: FastAPI = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.DEBUG,
        log_level=settings.log_level.lower(),
        access_log=settings.DEBUG,
    )
