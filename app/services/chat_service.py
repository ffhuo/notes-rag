"""业务·问答 — 检索增强问答编排（功能需求 FR3，SSE 流式）。

能力：
- 检索相关片段（retrieval_service）→ 拼接 system Prompt + 上下文 + 历史
- 调 LLM 流式生成（llm_client），逐 token 产出；**本次用哪个 LLM 由 llm_runtime 决定**（见 §18.2）
- 保存对话历史与来源（conversation_repo）
- 以事件流向外输出：{type:"sources"} / {type:"token"} / {type:"done"} / {type:"error"}

主要函数：
- async def stream(query, *, session, user_id, conversation_id, top_k, vault_id,
                   embed_runtime, llm_runtime) -> AsyncIterator[dict]: 流式事件生成器
      embed_runtime 按 vault.embed_profile_id 解析并经兼容性守卫（检索侧绑定）；
      llm_runtime 由 model_service.resolve_profile(kind='llm', ref=request.llm_profile) 解析

事件约定：
- {"type": "sources", "data": [ChunkHit...]}：检索命中，先于 token 推送
- {"type": "token", "data": "片段"}：LLM 流式输出
- {"type": "done", "data": {"conversation_id": int}}：正常结束
- {"type": "error", "data": "错误信息"}：异常结束

关联方案：docs/design.md §5.3（Chat·SSE 流式）、§10 模块索引 M05 / M08。
"""
from collections.abc import AsyncIterator

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import ModelRuntime
from app.rag import llm_client
from app.repositories import conversation_repo
from app.services import retrieval_service

# 拼接历史时最多带入的历史消息条数（user+assistant 合计），避免上下文无限膨胀
_HISTORY_LIMIT = 10

_SYSTEM_PROMPT = """你是一个严谨的知识库问答助手。请仅依据下方「参考资料」回答用户问题。

要求：
1. 答案必须基于参考资料，不得编造资料中没有的事实；
2. 若参考资料不足以回答，明确告知用户「根据现有资料无法回答」；
3. 回答使用简体中文，条理清晰，必要时分点说明。"""


def _build_context(hits: list) -> str:
    """把检索命中拼成带编号的上下文块。"""
    blocks = []
    for i, hit in enumerate(hits, start=1):
        source = getattr(hit, "file_path", "") or getattr(hit, "title", "")
        blocks.append(f"[{i}] 来源：{source}\n{hit.content}")
    return "\n\n".join(blocks)


async def stream(
    query: str,
    *,
    session: AsyncSession,
    user_id: str = "default",
    conversation_id: int | None = None,
    top_k: int = 5,
    vault_id: int | None = None,
    embed_runtime: ModelRuntime | None = None,
    embed_profile_id: int | str | None = None,
    llm_runtime: ModelRuntime | None = None,
) -> AsyncIterator[dict]:
    """RAG 问答流式事件生成器。

    Args:
        query: 用户问题
        session: 数据库会话（读写对话历史）
        user_id: 用户标识（多用户隔离）
        conversation_id: 已有对话 id；None 表示新建对话
        top_k: 检索片段数
        vault_id: 限定检索的 vault
        embed_runtime: 检索用 embedding 运行时（须与建索引模型一致）
        llm_runtime: 生成用 LLM 运行时

    Yields:
        SSE 事件 dict：sources / token / done / error
    """
    if not query or not query.strip():
        yield {"type": "error", "data": "query 不能为空"}
        return
    if llm_runtime is None:
        yield {"type": "error", "data": "未配置 LLM 模型（llm_runtime 为空）"}
        return

    try:
        # 1) 对话：复用或新建
        if conversation_id is None:
            conv = await conversation_repo.new_conversation(session, user_id, vault_id)
            conversation_id = conv.id
            history: list = []
        else:
            history = await conversation_repo.get_history(session, conversation_id)

        # 2) 检索
        hits = await retrieval_service.retrieve(
            query,
            top_k=top_k,
            vault_id=vault_id,
            embed_profile_id=embed_profile_id,
            embed_runtime=embed_runtime,
        )

        # 按检索命中组装来源：字段与 ChunkHit 对齐（含 content），
        # 前端「来源」展开要显示片段原文；漏掉 content 会让展开后一片空白
        sources = [
            {
                "note_id": h.note_id,
                "file_path": h.file_path,
                "title": h.title,
                "content": h.content,
                "score": h.score,
                "images": h.images,
            }
            for h in hits
        ]
        yield {"type": "sources", "data": sources}

        # 3) 拼消息：system（含资料）+ 历史 + 当前问题
        context = _build_context(hits)
        messages: list[dict] = [
            {"role": "system", "content": f"{_SYSTEM_PROMPT}\n\n===== 参考资料 =====\n{context}"},
        ]
        for msg in history[-_HISTORY_LIMIT:]:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": query})

        # 4) 流式生成并累积完整答案
        answer_parts: list[str] = []
        async for piece in llm_client.stream_chat(messages, llm_runtime):
            answer_parts.append(piece)
            yield {"type": "token", "data": piece}

        answer = "".join(answer_parts)

        # 5) 持久化：用户问题 + 助手回答
        await conversation_repo.append_message(
            session, conversation_id, "user", query, user_id=user_id
        )
        await conversation_repo.append_message(
            session, conversation_id, "assistant", answer, user_id=user_id
        )

        logger.info(
            "chat 完成",
            conversation_id=conversation_id,
            hits=len(hits), answer_chars=len(answer),
            model=llm_runtime.model,
        )
        yield {"type": "done", "data": {"conversation_id": conversation_id}}

    except Exception as e:
        logger.error("chat 失败", error=str(e), conversation_id=conversation_id)
        yield {"type": "error", "data": str(e)}
