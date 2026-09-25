"""路由聚合 — 将各业务路由合并为一个 APIRouter，供 main.py 引用。"""
from fastapi import APIRouter

from app.api.routes import auth, chat, health, ingest, models, search, vaults

router = APIRouter()
router.include_router(health.router)
router.include_router(ingest.router)
router.include_router(search.router)
router.include_router(chat.router)
router.include_router(vaults.router)
router.include_router(auth.router)
router.include_router(models.router)
