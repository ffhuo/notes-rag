"""业务·模型配置 — 多 LLM / 多 Embedding 的解析与选择（见 design.md §18）。

能力：
- 解析「本次请求用哪个模型」：请求参数 → 用户默认 → 系统种子（三级，见 §18.3）
- 把 ModelProfile 解析成 ModelRuntime（端点 / 密钥取配置自身值），rag 层只认 ModelRuntime
- 构造 OpenAI 兼容客户端（AsyncOpenAI），供 embedder / llm_client 使用
- **embedding 一致性守卫**：检索必须用「建该 vault 索引时那个」embedding，换模型需先重建索引（§18.2）

主要函数：
- async def resolve_profile(session, settings, kind, ref=None, user_id="default") -> ModelProfile
- def to_runtime(profile) -> ModelRuntime
- def build_client(runtime) -> AsyncOpenAI
- def assert_embed_compatible(vault, profile) -> None
- def collection_name(vault_id, profile_id) -> str
- async def list_models / create_model / update_model / delete_model / set_default：CRUD 编排
- async def test_connection(runtime) -> ModelTestResult

关联方案：docs/design.md §18（多模型管理）、§7（RAG 管线）。
"""
import json
import time

from pydantic import SecretStr

from app.core.config import Settings
from app.models import ModelProfile, Vault
from app.models.schemas import (
    ModelProfileCreate,
    ModelProfileOut,
    ModelProfileUpdate,
    ModelRuntime,
    ModelTestResult,
)
from app.rag.client import build_client  # noqa: F401  re-export，供其他 service 使用
from app.rag.embedder import embed_one
from app.rag.llm_client import chat
from app.repositories import model_repo


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


# ===== 解析（三级：ref → 默认 → 兜底）=====


async def resolve_profile(
    session,
    settings: Settings,
    kind: str,
    ref: str | None = None,
    user_id: str = "default",
) -> ModelProfile:
    """解析「本次请求用哪个模型」。

    1) 显式指定：ref 为纯数字按 id 找，否则按 name 找；找不到抛 ModelNotFound
    2) 未指定：取该 (user_id, kind) 的 is_default 项
    3) 再没有：取该 kind 第一条 enabled 项
    4) 表为空：抛 ModelNotConfigured，由调用方转 409 提示到「模型」页配置
    """
    if ref is not None:
        # 显式指定：数字按 id，否则按 name
        if ref.isdigit():
            profile = await model_repo.get_profile(session, int(ref), user_id)
        else:
            profile = await model_repo.find_by_name(session, user_id, kind, ref)
        if profile is None:
            raise ModelNotFound(f"kind={kind} ref={ref} 找不到模型配置")
        return profile

    # 取默认项
    profile = await model_repo.get_default(session, user_id, kind)
    if profile is not None:
        return profile

    # 取第一条 enabled
    profiles = await model_repo.list_profiles(session, user_id, kind, only_enabled=True)
    if profiles:
        return profiles[0]

    raise ModelNotConfigured(f"kind={kind} 无任何可用模型配置")


def to_runtime(profile: ModelProfile) -> ModelRuntime:
    """profile → 运行时配置：端点 / 密钥直接取配置自身值（不再回退 .env）。"""
    params = {}
    if profile.params_json and profile.params_json != "{}":
        try:
            params = json.loads(profile.params_json)
        except (json.JSONDecodeError, TypeError):
            pass

    return ModelRuntime(
        kind=profile.kind,
        name=profile.name,
        base_url=profile.base_url or "",
        api_key=SecretStr(profile.api_key or ""),
        model=profile.model,
        params=params,
    )


def assert_embed_compatible(vault: Vault, profile: ModelProfile) -> None:
    """检索前守卫：vault 必须用该 embedding 模型建过索引，否则抛 EmbedModelMismatch。

    判定：profile.id ∈ json.loads(vault.embed_indexed_profiles or "[]")
    """
    indexed = json.loads(vault.embed_indexed_profiles or "[]")
    if profile.id not in indexed:
        raise EmbedModelMismatch(
            f"vault(id={vault.id}) 未用 embedding(id={profile.id}, name={profile.name!r}) 建过索引；"
            f"已建索引的 profile ids: {indexed}。请先 reindex。"
        )


# ===== CRUD 编排 =====


def _to_out(profile: ModelProfile) -> ModelProfileOut:
    """ModelProfile → ModelProfileOut（api_key 脱敏）。"""
    params = {}
    if profile.params_json and profile.params_json != "{}":
        try:
            params = json.loads(profile.params_json)
        except (json.JSONDecodeError, TypeError):
            pass

    return ModelProfileOut(
        id=profile.id,
        kind=profile.kind,
        name=profile.name,
        provider=profile.provider,
        base_url=profile.base_url,
        model=profile.model,
        params=params,
        is_default=profile.is_default,
        enabled=profile.enabled,
        origin=profile.origin,
        api_key_masked=mask_api_key(profile.api_key),
    )


def to_out(profile: ModelProfile) -> ModelProfileOut:
    """ModelProfile → ModelProfileOut（api_key 脱敏）。

    对外暴露：API 层按 id 取单个配置时复用同一份脱敏 / params 解析规则，
    避免路由里再写一遍（出参永不返回明文 api_key，§18.6）。
    """
    return _to_out(profile)


async def list_models(session, user_id: str, kind: str | None = None) -> list[ModelProfileOut]:
    """列出当前用户的模型配置（可按 kind=llm|embed 过滤）。"""
    profiles = await model_repo.list_profiles(session, user_id, kind, only_enabled=True)
    return [_to_out(p) for p in profiles]


async def create_model(
    session, settings: Settings, user_id: str, data: ModelProfileCreate
) -> ModelProfileOut:
    """创建模型配置。base_url / api_key 为空是允许的：base_url 空 = OpenAI 官方端点，
    api_key 空 = 不带鉴权（第三方服务通常必填）。"""
    params_json = json.dumps(data.params) if data.params else "{}"
    profile = await model_repo.create_profile(
        session,
        user_id=user_id,
        kind=data.kind,
        name=data.name,
        model=data.model,
        provider=data.provider,
        base_url=data.base_url,
        api_key=data.api_key,
        params_json=params_json,
        is_default=data.set_default,
    )
    return _to_out(profile)


async def update_model(
    session, profile: ModelProfile, data: ModelProfileUpdate
) -> ModelProfileOut:
    """局部更新模型配置。"""
    patch = {}
    if data.name is not None:
        patch["name"] = data.name
    if data.model is not None:
        patch["model"] = data.model
    if data.base_url is not None:
        patch["base_url"] = data.base_url
    if data.api_key is not None:
        patch["api_key"] = data.api_key
    if data.params is not None:
        patch["params_json"] = json.dumps(data.params)
    if data.enabled is not None:
        patch["enabled"] = data.enabled

    if patch:
        profile = await model_repo.update_profile(session, profile, patch)

    if data.set_default is True:
        await model_repo.set_default(session, profile)

    return _to_out(profile)


async def delete_model(session, profile: ModelProfile) -> None:
    """删除模型配置。

    注意：若该 profile 还被 vault.embed_profile_id 引用，应拒绝删除或提示先换模型重建索引。
    """
    await model_repo.delete_profile(session, profile)


async def set_default(session, user_id: str, kind: str, profile: ModelProfile) -> ModelProfileOut:
    """设为该 kind 的默认项。"""
    await model_repo.set_default(session, profile)
    return _to_out(profile)


async def test_connection(runtime: ModelRuntime) -> ModelTestResult:
    """连通性测试：embed 试 1 条，llm 试极短对话，asr 只探端点。

    asr 刻意不做真实转写：那需要造一段音频，且按秒计费 ——
    用 GET /models 验证「端点可达 + 鉴权有效」就够了，识别质量由实际使用检验。
    """
    start = time.monotonic()

    try:
        if runtime.kind == "embed":
            await embed_one("test", runtime)
        elif runtime.kind == "asr":
            client = build_client(runtime)
            await client.models.list()
        else:
            await chat(
                [{"role": "user", "content": "hi"}],
                runtime,
                max_tokens=1,
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return ModelTestResult(ok=True, model=runtime.model, elapsed_ms=elapsed)
    except Exception as e:
        elapsed = int((time.monotonic() - start) * 1000)
        return ModelTestResult(ok=False, model=runtime.model, elapsed_ms=elapsed, error=str(e))
