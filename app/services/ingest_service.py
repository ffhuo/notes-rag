"""业务·摄取 — 编排笔记/文档索引全流程（功能需求 FR1，docs/design.md §4.1 / §16）。

能力：
- 扫描 vault 来源下的文件（递归），应用过滤（排除目录 / 扩展名白名单 / include-exclude glob，见 §16.3）
- 按扩展名路由解析器（app/parsers/*）得到纯文本 → 分块（chunker）→ 嵌入（embedder）
  → 写向量库（vectorstore）→ 写元数据（note_repo）
- 支持全量重建（rebuild）与增量跳过未变更文件
- 统计扫描数与索引分块数，供接口返回
- index_vault：面向「前端管理的 vault 实体」，先由 vault_service 解析出本地路径，再复用 scan 的索引逻辑
- **embedding 模型绑定**：索引时确定 embed_runtime，写入 chunks.embed_profile_id 与
  vault.embed_indexed_profiles，向量落在 collection_name(vault_id, profile_id)（见 §18.2）

主要函数：
- async def scan(vault_sources, rebuild, filters, embed_runtime=None) -> IngestResponse: 编排整个 ingest 流程（兼容命令行 / MCP 直接传 vault_sources）
- async def index_vault(vault, local_path, rebuild, filters, embed_runtime=None) -> IngestResponse: 由 vault 实体触发索引（前端 vaults + reindex 走此，见 §17.2）
      embed_runtime 由 model_service.to_runtime(resolve_profile(kind='embed')) 解析后传入；
      索引完成后需把 profile.id 追加进 vault.embed_indexed_profiles 并置为 vault.embed_profile_id

关联方案：docs/design.md §4.1（Ingest 时序）、§9（Phase 1）、§16（多格式与过滤）、§17.2（vault 管理）、§18（多模型）。
"""
from pathlib import Path
from typing import Optional

from app.models.orm import Vault
from app.models.schemas import IngestFilters, IngestResponse, ModelRuntime


async def scan(vault_sources: list[str], rebuild: bool = False,
               filters: "IngestFilters | None" = None,
               embed_runtime: "ModelRuntime | None" = None) -> IngestResponse:
    ...


async def index_vault(vault: Vault, local_path: Path, rebuild: bool = False,
                      filters: "Optional[IngestFilters]" = None,
                      embed_runtime: "ModelRuntime | None" = None) -> IngestResponse:
    # 复用 scan 的内部索引逻辑：local_path 即 vault 解析后的本地目录
    ...

