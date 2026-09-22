"""路由·检索 — POST /api/v1/search。

能力：
- 接收 query / top_k / threshold，返回语义检索命中
- 受 API Key 保护（依赖 get_current_api_key）

主要端点：
- POST /api/v1/search → 调用 retrieval_service.retrieve

关联方案：docs/design.md §4.2（Search 时序）、§5（API 设计）。
"""
from fastapi import APIRouter

from app.api.deps import get_current_api_key
from app.models.schemas import SearchRequest, SearchResponse
from app.services import retrieval_service

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, _: str = get_current_api_key()) -> SearchResponse:
    ...
