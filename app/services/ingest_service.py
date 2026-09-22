"""业务·摄取 — 编排笔记索引全流程（功能需求 FR1）。

能力：
- 扫描 vault 目录下的 .md 文件（递归）
- 解析 → 分块（chunker）→ 嵌入（embedder）→ 写向量库（vectorstore）→ 写元数据（note_repo）
- 支持全量重建（rebuild）与增量跳过未变更文件
- 统计扫描数与索引分块数，供接口返回

主要函数：
- async def scan(vault_path: str, rebuild: bool = False) -> IngestResponse: 编排整个 ingest 流程

关联方案：docs/design.md §4.1（Ingest 时序）、§9（Phase 1）。
"""
from app.models.schemas import IngestResponse


async def scan(vault_path: str, rebuild: bool = False) -> IngestResponse:
    ...
