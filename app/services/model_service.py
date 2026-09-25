"""业务·模型配置 — 多 LLM / 多 Embedding 的解析与选择（见 design.md §18）。

能力：
- 解析「本次请求用哪个模型」：请求参数 → 用户默认 → 系统种子（三级，见 §18.3）
- 把 ModelProfile 解析成 ModelRuntime（应用端点/密钥回退），rag 层只认 ModelRuntime
- 构造 OpenAI 兼容客户端（AsyncOpenAI），供 embedder / llm_client 使用
- **embedding 一致性守卫**：检索必须用「建该 vault 索引时那个」embedding，换模型需先重建索引（§18.2）
- 表空时用 .env 的 LLM_* / EMBED_* 构造临时运行时配置（runtime_from_settings 兜底）

主要函数：
- async def resolve_profile(session, settings, kind, ref=None, user_id="default") -> ModelProfile
      ref 可为 id 或 name；留空取该 kind 的默认项；都没配则回退 settings 构造的临时配置
- def to_runtime(profile, settings) -> ModelRuntime：应用 base_url / api_key 回退
- def runtime_from_settings(settings, kind) -> ModelRuntime：表为空时的兜底
- def build_client(runtime) -> AsyncOpenAI
- def assert_embed_compatible(vault, profile) -> None：不一致则抛 EmbedModelMismatch
- def collection_name(vault_id, profile_id) -> str：向量集合命名（模型隔离，见 §18.2）
- async def list_models / create_model / update_model / delete_model / set_default：CRUD 编排
- async def test_connection(runtime) -> ModelTestResult：连通性测试（embed 试 1 条，llm 试极短对话）

关联方案：docs/design.md §18（多模型管理）、§7（RAG 管线）。
"""
import json

from openai import AsyncOpenAI

from app.core.config import Settings
from app.models.orm import ModelProfile, Vault
from app.models.schemas import (
    ModelProfileCreate,
    ModelProfileOut,
    ModelProfileUpdate,
    ModelRuntime,
    ModelTestResult,
)
from app.repositories import model_repo
from pydantic import SecretStr


class ModelNotFound(Exception):
    """按 name / id 找不到对应的模型配置。"""


class ModelNotConfigured(Exception):
    """该 kind 一个可用配置都没有（既无 profile，也无法从 settings 兜底）。"""


class EmbedModelMismatch(Exception):
    """vault 的索引不是用当前 embedding 模型建的 —— 需先重建索引。"""


def collection_name(vault_id: int | str, profile_id: int | str) -> str:
    """向量集合名：按 (vault, embedding 模型) 隔离，避免不同模型的向量混在一个空间里。"""
    return f"v{vault_id}_m{profile_id}"


def mask_api_key(key: str) -> str:
    """脱敏展示：sk-abcdefghijkl → sk-ab****kl；空串返回空串。"""
    if not key:
        return ""
    if len(key) <= 8:
        return key[0] + "*" * (len(key) - 1)
    return f"{key[:4]}****{key[-2:]}"


async def resolve_profile(
    session,
    settings: Settings,
    kind: str,
    ref: str | None = None,
    user_id: str = "default",
) -> ModelProfile:
    # 1) 显式指定：ref 为纯数字按 id 找，否则按 name 找；找不到抛 ModelNotFound
    # 2) 未指定：取该 (user_id, kind) 的 is_default 项
    # 3) 再没有：取该 kind 第一条 enabled 项
    # 4) 表为空：抛出 ModelNotConfigured，由调用方用 runtime_from_settings 兜底
    ...


def to_runtime(profile: ModelProfile, settings: Settings) -> ModelRuntime:
    """profile → 运行时配置：base_url / api_key 留空时回退 .env 的同 kind 配置。"""
    ...


def runtime_from_settings(settings: Settings, kind: str) -> ModelRuntime:
    """表为空时的兜底：直接用 .env 的 LLM_* / EMBED_* 构造运行时配置。"""
    ...


def build_client(runtime: ModelRuntime) -> AsyncOpenAI:
    """构造 OpenAI 兼容客户端（Qwen / vLLM / 本地服务均走同一协议）。"""
    ...


def assert_embed_compatible(vault: Vault, profile: ModelProfile) -> None:
    """检索前守卫：vault 必须用该 embedding 模型建过索引，否则抛 EmbedModelMismatch。

    判定：profile.id ∈ json.loads(vault.embed_indexed_profiles or "[]")
    修复路径：对该 vault 用该 profile 重新 ingest（POST /api/v1/vaults/{id}/reindex?embed_profile=...）
    """
    ...


async def list_models(session, user_id: str, kind: str | None = None) -> list[ModelProfileOut]:
    """列出当前用户的模型配置（可按 kind=llm|embed 过滤）。"""
    return model_repo.list_profiles(session, user_id, kind, True)


async def create_model(
    session, settings: Settings, user_id: str, data: ModelProfileCreate
) -> ModelProfileOut:
    # base_url / api_key 为空是允许的（表示回退 .env），落库时保持空串
    ...


async def update_model(
    session, profile: ModelProfile, data: ModelProfileUpdate
) -> ModelProfileOut:
    ...


async def delete_model(session, profile: ModelProfile) -> None:
    # 注意：若该 profile 还被 vault.embed_profile_id 引用，应拒绝删除或提示先换模型重建索引
    ...


async def set_default(session, profile: ModelProfile) -> ModelProfileOut:
    ...


async def test_connection(runtime: ModelRuntime) -> ModelTestResult:
    # embed：embed 一条短文本，返回维度；llm：极小 max_tokens 试一次，返回首块内容
    ...
