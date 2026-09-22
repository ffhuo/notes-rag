"""业务·问答 — 检索增强问答编排（功能需求 FR3，SSE 流式）。

能力：
- 检索相关片段（retrieval_service）→ 拼接 system Prompt + 上下文 + 历史
- 调 LLM 流式生成（llm_client），逐 token 产出
- 保存对话历史与来源（conversation_repo）
- 以事件流向外输出：{type:"token"} / {type:"sources"} / {type:"done"}

主要函数：
- async def stream(query: str, conversation_id: str | None = None, top_k: int = 5) -> AsyncIterator[dict]: 流式事件生成器

关联方案：docs/design.md §4.3（Chat 时序）、§7（RAG 管线·Prompt/流式）、§9（Phase 3）。
"""
async def stream(query: str, conversation_id: str | None = None, top_k: int = 5):
    ...
