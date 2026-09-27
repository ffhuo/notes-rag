"""embedder 单元测试 — 直连一个真实的 OpenAI 兼容 embedding 端点。

运行方式：
    TEST_EMBED_BASE_URL=https://api.siliconflow.cn/v1 \
    TEST_EMBED_API_KEY=sk-xxx \
    TEST_EMBED_MODEL=BAAI/bge-m3 \
    .venv/bin/python -m pytest tests/test_embedder.py -v -s

未设置上述环境变量时整文件 skip（默认跑测试不需要网络与密钥）。

注意：这里读环境变量**仅为本测试自备凭据**，与运行时配置无关 ——
运行时的模型配置一律来自 model_profiles 表（§18），不再有 .env 兜底。
"""
import asyncio
import os

import pytest
from pydantic import SecretStr

from app.models.schemas import ModelRuntime
from app.rag.embedder import embed

_BASE_URL = os.environ.get("TEST_EMBED_BASE_URL", "")
_API_KEY = os.environ.get("TEST_EMBED_API_KEY", "")
_MODEL = os.environ.get("TEST_EMBED_MODEL", "")

pytestmark = pytest.mark.skipif(
    not (_BASE_URL and _API_KEY and _MODEL),
    reason="未设置 TEST_EMBED_BASE_URL / TEST_EMBED_API_KEY / TEST_EMBED_MODEL，跳过联网用例",
)

# 由上述环境变量构建 runtime
_runtime = ModelRuntime(
    kind="embed",
    name="test-embed",
    base_url=_BASE_URL,
    api_key=SecretStr(_API_KEY),
    model=_MODEL,
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
