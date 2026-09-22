"""RAG·嵌入 — 文本转向量（OpenAI 兼容 embedding，异步）。

能力：
- 批量将文本片段转为 embedding 向量
- 指向可配置的 embedding 模型端点（见 Settings.embed_model）
- 控制并发 / 限速，避免触发接口限流

主要函数：
- async def embed(texts: list[str]) -> list[list[float]]: 异步返回向量列表

关联方案：docs/design.md §3（技术选型）、§7（RAG 管线设计·嵌入）。
"""
from openai import AsyncOpenAI

from app.core.config import Settings  # 或 settings 单例


async def embed(texts: list[str]) -> list[list[float]]:
    ...
