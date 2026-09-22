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
from openai import AsyncOpenAI

from app.models.schemas import ModelRuntime


async def stream_chat(messages: list[dict], runtime: "ModelRuntime"):
    ...
