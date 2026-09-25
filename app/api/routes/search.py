"""路由·检索 — POST /api/v1/search。

能力：
- 接收 query / top_k / threshold / vault_id，返回语义检索命中
- 受 API Key 保护（依赖 get_current_api_key）
- **embedding 不由请求指定**：必须沿用该 vault 建索引时的模型，故接口不暴露 embed_profile（§18.2）；
  由 model_service 按 vault.embed_profile_id 解析并做 assert_embed_compatible 守卫

主要端点：
- POST /api/v1/search → 解析 embed_runtime 后调 retrieval_service.retrieve

关联方案：docs/design.md §4.2（Search 时序）、§5（API 设计）、§18（多模型管理）。
"""
from fastapi import APIRouter, Depends

from app.api.deps import get_current_api_key
from app.models.schemas import SearchRequest, SearchResponse
from app.services import retrieval_service

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest, _: str = Depends(get_current_api_key)) -> SearchResponse:
    ...
