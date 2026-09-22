"""业务·问答 — 检索增强问答编排（功能需求 FR3，SSE 流式）。

能力：
- 检索相关片段（retrieval_service）→ 拼接 system Prompt + 上下文 + 历史
- 调 LLM 流式生成（llm_client），逐 token 产出；**本次用哪个 LLM 由 llm_runtime 决定**（见 §18.2）
- 保存对话历史与来源（conversation_repo）
- 以事件流向外输出：{type:"token"} / {type:"sources"} / {type:"done"}

主要函数：
- async def stream(query, conversation_id=None, top_k=5, vault_id=None, llm_runtime=None): 流式事件生成器
      llm_runtime 由 model_service.resolve_profile(kind='llm', ref=request.llm_profile) 解析；
      留空即取当前用户的默认 LLM

关联方案：docs/design.md §4.3（Chat 时序）、§7（RAG 管线·Prompt/流式）、§9（Phase 3）、§18（多模型）。
"""
from app.models.schemas import ModelRuntime


async def stream(query: str, conversation_id: str | None = None, top_k: int = 5,
                 vault_id: str | None = None,
                 llm_runtime: "ModelRuntime | None" = None):
    ...
