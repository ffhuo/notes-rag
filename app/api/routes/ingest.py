"""路由·摄取 — POST /api/v1/ingest。

能力：
- 接收 vault_path / vault_sources / vault_id / rebuild / filters / embed_profile，触发笔记索引
- 返回扫描文件数与索引分块数（IngestResponse）
- 受 API Key 保护（依赖 get_current_api_key）
- **建索引用哪个 embedding**：req.embed_profile（name 或 id）→ 用户默认 → .env 兜底（§18.3）；
  索引写入 collection_name(vault_id, profile.id)，并把 profile.id 记入 vault.embed_indexed_profiles

主要端点：
- POST /api/v1/ingest → 解析 embed_runtime 后调 ingest_service.scan

关联方案：docs/design.md §4.1（Ingest 时序）、§5（API 设计）、§18（多模型管理）。
"""
from fastapi import APIRouter

from app.api.deps import get_current_api_key
from app.models.schemas import IngestRequest, IngestResponse
from app.services import ingest_service

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest, _: str = get_current_api_key()) -> IngestResponse:
    ...
