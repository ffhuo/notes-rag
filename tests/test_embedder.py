"""embedder 单元测试 — 使用 .env 中的硅基流动 embedding 配置执行。

运行方式：
    .venv/bin/python -m pytest tests/test_embedder.py -v -s

需要网络连接和有效的 EMBED_API_KEY。
"""
import asyncio

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.models.schemas import ModelRuntime
from app.rag.embedder import embed

# 从 .env 配置构建 runtime
_runtime = ModelRuntime(
    kind="embed",
    name="test-siliconflow",
    base_url=settings.get_embed_base_url(),
    api_key=settings.get_embed_api_key(),
    model=settings.embed_model,
    params={"timeout": 30},
)


def test_empty_texts():
    """空列表返回空向量列表。"""
    result = asyncio.run(embed([], _runtime))
    assert result == []


def test_single_text():
    """单条文本嵌入。"""
    vectors = asyncio.run(embed(["你好，世界"], _runtime))
    assert len(vectors) == 1
    assert len(vectors[0]) > 0  # BGE-M3 输出 1024 维
    # 打印维度供人工确认
    print(f"\n[BGE-M3] dim={len(vectors[0])}")


def test_batch_embed():
    """批量嵌入：多条文本一次请求。"""
    texts = ["Python 是一门编程语言", "Go 语言简洁高效", "Rust 注重内存安全"]
    vectors = asyncio.run(embed(texts, _runtime, batch_size=3))
    assert len(vectors) == 3
    assert all(len(v) == len(vectors[0]) for v in vectors)  # 维度一致


def test_large_batch_splits():
    """超过 batch_size 的列表自动分批。"""
    texts = [f"测试文本第{i}条" for i in range(10)]
    vectors = asyncio.run(embed(texts, _runtime, batch_size=3))
    assert len(vectors) == 10
    assert all(len(v) == len(vectors[0]) for v in vectors)


def test_order_preserved():
    """向量顺序与输入文本一一对应。"""
    texts = ["苹果", "香蕉", "橙子"]
    vectors = asyncio.run(embed(texts, _runtime, batch_size=1))
    assert len(vectors) == 3
    # 不同文本的向量不应完全相同
    assert vectors[0] != vectors[1]
    assert vectors[1] != vectors[2]


def test_runtime_validation():
    """缺少 base_url 或 model 时抛 ValueError。"""
    bad = ModelRuntime(
        kind="embed", name="bad", base_url="",
        api_key=SecretStr(""), model="",
    )
    with pytest.raises(ValueError):
        asyncio.run(embed(["test"], bad))
