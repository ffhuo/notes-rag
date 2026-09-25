"""路由·健康检查 — GET /healthz。

能力：
- 探活，返回 {"status": "ok"}
- 免鉴权（不依赖 get_current_api_key）

主要端点：
- GET /healthz

关联方案：docs/design.md §5（API 设计）。
"""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def health() -> dict:
    """健康检查，返回 {"status": "ok"}。"""
    return {"status": "ok"}
