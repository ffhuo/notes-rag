"""业务·vault 管理 — 把「前端配置的 vault」解析为可索引的本地路径并触发摄取（功能需求 §17.2）。

能力：
- 把 Vault（DB 实体）解析为本地目录路径：
  - local：直接返回 source_value（绝对路径）
  - uploaded：返回 UPLOAD_DIR/<vault_id>（上传时解压到的目录）
  - git / remote：首次 clone/pull 或下载到缓存目录，返回该目录
- 接收上传的 vault 压缩包 → 解压到 UPLOAD_DIR/<vault_id>
- 触发重建索引：解析路径 → 调 ingest_service.index_vault（复用 §4.1 管线）

主要函数：
- async def resolve_local_path(vault: Vault) -> Path: 由 source_type 解析本地目录
- async def save_upload(vault_id: str, file) -> Path: 接收 zip → 解压到 UPLOAD_DIR/<vault_id>
- async def reindex(vault, settings, rebuild=False, filters=None, embed_profile=None) -> IngestResponse: 编排索引
      embed_profile 指定用哪个 embedding 建索引；不传则取当前默认 embed 配置（§18.3）
- async def seed_from_env(session, settings) -> list[Vault]: 一次性注入 .env 种子（见下方规则）

关联方案：docs/design.md §17.2（vault 管理）、§16（解析层）、§4.1（ingest 时序）、§18（多模型）。
"""
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.orm import ModelProfile, Vault
from app.models.schemas import IngestFilters, IngestResponse


def resolve_local_path(vault: Vault, settings: Settings) -> Path:
    ...


async def save_upload(vault_id: str, file: Any, settings: Settings) -> Path:
    # 接收 multipart 的 .zip → 解压到 settings.upload_dir/<vault_id>
    ...


async def seed_from_env(
    session: AsyncSession, settings: Settings
) -> list[Vault]:
    """把 .env 的 VAULT_SOURCES 作为**一次性 bootstrap 种子**写入 vaults 表。

    规则（design.md §17.2）：
    - **DB 是唯一运行时真相源**，.env 只是冷启动用的种子，不是权威。
    - 仅当 vaults 表**为空**时注入一次（count_vaults() == 0）；之后前端增删说了算，
      用户删掉的种子 vault **不会被复活**。
    - 注入的记录 origin="env"，前端可标注「来自环境变量」。
    - 例外：无头模式（UI_ENABLED=false）没有 UI 可改，每次启动按 source_value 对账
      （find_by_source 查重后 upsert），保证改 .env 后重启能生效。
    - 种子统一归 user_id="default"（单用户 owner）。
    """
    ...


async def reindex(
    vault: Vault,
    settings: Settings,
    rebuild: bool = False,
    filters: "IngestFilters | None" = None,
    embed_profile: "ModelProfile | None" = None,
) -> IngestResponse:
    # 1) 解析本地路径（resolve_local_path）
    # 2) 解析 embedding 配置：embed_profile 或 resolve_profile(kind='embed')，
    #    再 model_service.to_runtime() 得到 embed_runtime
    # 3) 调 ingest_service.index_vault(vault, local_path, rebuild, filters, embed_runtime)
    # 4) 更新 vault.indexed_at / embed_profile_id，并把 profile.id 追加进 embed_indexed_profiles
    ...
