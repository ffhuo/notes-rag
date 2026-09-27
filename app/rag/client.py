"""RAG·客户端工厂 — OpenAI 兼容客户端的唯一构造点。

embedder / llm_client / model_service 均从这里获取 AsyncOpenAI，
避免在多处重复实例化逻辑（base_url / api_key / timeout 处理）。
"""
from openai import AsyncOpenAI

from app.models.schemas import ModelRuntime


def build_client(runtime: ModelRuntime) -> AsyncOpenAI:
    """构造 OpenAI 兼容客户端（Qwen / vLLM / 本地服务均走同一协议）。"""
    kwargs: dict = {"api_key": runtime.api_key.get_secret_value()}
    # base_url 留空 = 用 SDK 默认端点（api.openai.com）；有值则显式覆盖
    if runtime.base_url:
        kwargs["base_url"] = runtime.base_url
    if "timeout" in runtime.params:
        kwargs["timeout"] = runtime.params["timeout"]
    return AsyncOpenAI(**kwargs)
