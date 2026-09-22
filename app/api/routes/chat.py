"""路由·问答 — POST /api/v1/chat（SSE 流式）。

能力：
- 接收 query / conversation_id / top_k / vault_id / llm_profile
- 以 text/event-stream 流式返回：token 片段 / sources 来源 / done 结束
- 受 API Key 保护（依赖 get_current_api_key）
- 用 StreamingResponse 包装 chat_service.stream 的生成器
- **本次用哪个 LLM**：req.llm_profile（name 或 id）→ 用户默认 → .env 兜底（见 §18.3）

主要端点：
- POST /api/v1/chat → 解析 llm_runtime 后调 chat_service.stream，包装为 SSE

关联方案：docs/design.md §4.3（Chat 时序）、§5（API 设计）、§18（多模型管理）。
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_api_key
from app.models.schemas import ChatRequest
from app.services import chat_service

router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat")
async def chat(req: ChatRequest, _: str = get_current_api_key()) -> StreamingResponse:
    ...
