"""RAG·LLM — 调用大模型生成回答（流式 / 非流式）。

能力：
- stream_chat：以 stream=True 调用 chat.completions，异步 yield 每个 token
- chat：非流式调用，返回完整文本（供 test_connection 等场景）
- 接入运行时模型配置 ModelRuntime（由 model_service 解析本次用哪个 LLM，见 §18）

所有 AsyncOpenAI 客户端由 app.rag.client.build_client 统一构造，本模块不直接实例化。

主要函数：
- async def stream_chat(messages, runtime) -> AsyncIterator[str]: 流式返回文本片段
- async def chat(messages, runtime) -> str: 非流式返回完整文本

关联方案：docs/design.md §4.3（Chat 时序）、§7（RAG 管线设计·流式）、§18（多模型管理）。
"""
from collections.abc import AsyncIterator

from loguru import logger

from app.models.schemas import ModelRuntime
from app.rag.client import build_client


async def stream_chat(
    messages: list[dict],
    runtime: ModelRuntime,
) -> AsyncIterator[str]:
    """流式调用 LLM，逐 token yield 文本片段。

    Args:
        messages: OpenAI 格式消息列表 [{"role": "system", "content": "..."}, ...]
        runtime: 运行时模型配置（base_url / api_key / model / params）

    Yields:
        文本片段（delta content），供 SSE 对外推送

    Raises:
        ValueError: runtime 缺少必要字段
        RuntimeError: LLM 请求失败
    """
    if not runtime.base_url or not runtime.model:
        raise ValueError("runtime 缺少 base_url 或 model")

    model = runtime.model
    temperature = runtime.params.get("temperature", 0.7)
    max_tokens = runtime.params.get("max_tokens")
    top_p = runtime.params.get("top_p", 1.0)

    client = build_client(runtime)

    try:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "stream": True,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        stream = await client.chat.completions.create(**kwargs)

        total_chars = 0
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                total_chars += len(delta.content)
                yield delta.content

        logger.info(
            "stream_chat 完成",
            model=model, total_chars=total_chars,
        )

    except Exception as e:
        logger.error("stream_chat 请求失败", model=model, error=str(e))
        raise RuntimeError(f"LLM 请求失败: {e}") from e
    finally:
        await client.close()


async def chat(
    messages: list[dict],
    runtime: ModelRuntime,
    *,
    max_tokens: int | None = None,
) -> str:
    """非流式调用 LLM，返回完整文本。

    Args:
        messages: OpenAI 格式消息列表
        runtime: 运行时模型配置
        max_tokens: 覆盖 runtime.params 中的 max_tokens（如测试时设 1）

    Returns:
        模型返回的完整文本
    """
    if not runtime.base_url or not runtime.model:
        raise ValueError("runtime 缺少 base_url 或 model")

    model = runtime.model
    temperature = runtime.params.get("temperature", 0.7)
    top_p = runtime.params.get("top_p", 1.0)
    effective_max_tokens = max_tokens or runtime.params.get("max_tokens")

    client = build_client(runtime)

    try:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
        }
        if effective_max_tokens:
            kwargs["max_tokens"] = effective_max_tokens

        resp = await client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""

        logger.info("chat 完成", model=model, chars=len(content))
        return content

    except Exception as e:
        logger.error("chat 请求失败", model=model, error=str(e))
        raise RuntimeError(f"LLM 请求失败: {e}") from e
    finally:
        await client.close()
