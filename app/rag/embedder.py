"""RAG·嵌入 — 文本转向量（OpenAI 兼容 embedding，异步）。

能力：
- 批量将文本片段转为 embedding 向量
- 接入运行时模型配置 ModelRuntime（由 model_service 解析具体用哪个 embedding 模型，见 §18）
- 控制并发 / 限速，避免触发接口限流

主要函数：
- async def embed(texts: list[str], runtime: ModelRuntime) -> list[list[float]]: 异步返回向量列表
      runtime 决定 base_url / api_key / model；不传则不可用（由调用方显式选择模型）

关联方案：docs/design.md §3（技术选型）、§7（RAG 管线设计·嵌入）、§18（多模型管理）。
"""
from openai import AsyncOpenAI

from app.models.schemas import ModelRuntime


async def embed(texts: list[str], runtime: ModelRuntime) -> list[list[float]]:
    ...
