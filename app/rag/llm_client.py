"""RAG·LLM — 调用大模型生成回答（流式）。

能力：
- 以 stream=True 调用 chat.completions
- 异步 yield 每个 token 片段，供 SSE 对外流式输出
- 指向可配置的对话模型端点（见 Settings.llm_model）

主要函数：
- async def stream_chat(messages: list[dict]) -> AsyncIterator[str]: 流式返回文本片段

关联方案：docs/design.md §4.3（Chat 时序）、§7（RAG 管线设计·流式）。
"""
from openai import AsyncOpenAI

from app.core.config import Settings  # 或 settings 单例


async def stream_chat(messages: list[dict]) -> "AsyncIterator[str]":
    ...
