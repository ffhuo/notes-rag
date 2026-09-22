"""路由·摄取 — POST /api/v1/ingest。

能力：
- 接收 vault_path / rebuild，触发笔记索引
- 返回扫描文件数与索引分块数（IngestResponse）
- 受 API Key 保护（依赖 get_current_api_key）

主要端点：
- POST /api/v1/ingest → 调用 ingest_service.scan

关联方案：docs/design.md §4.1（Ingest 时序）、§5（API 设计）。
"""
from fastapi import APIRouter

from app.api.deps import get_current_api_key
from app.models.schemas import IngestRequest, IngestResponse
from app.services import ingest_service

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest, _: str = get_current_api_key()) -> IngestResponse:
    ...
