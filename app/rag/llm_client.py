"""RAG·LLM — 调用大模型生成回答（流式）。

能力：
- 以 stream=True 调用 chat.completions
- 异步 yield 每个 token 片段，供 SSE 对外流式输出
- 接入运行时模型配置 ModelRuntime（由 model_service 解析本次用哪个 LLM，见 §18）

主要函数：
- async def stream_chat(messages: list[dict], runtime: ModelRuntime) -> AsyncIterator[str]: 流式返回文本片段
      runtime 决定 base_url / api_key / model 与 temperature 等参数；每次请求可换模型

关联方案：docs/design.md §4.3（Chat 时序）、§7（RAG 管线设计·流式）、§18（多模型管理）。
"""
from collections.abc import AsyncIterator

from loguru import logger
from openai import AsyncOpenAI

from app.models.schemas import ModelRuntime


def _make_client(runtime: ModelRuntime) -> AsyncOpenAI:
    """根据 runtime 创建 AsyncOpenAI 客户端。"""
    return AsyncOpenAI(
        base_url=runtime.base_url,
        api_key=runtime.api_key.get_secret_value(),
        timeout=runtime.params.get("timeout", 120),
    )


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

    client = _make_client(runtime)

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
