"""业务·摄取原语 — 单个文件「怎么进 / 怎么出」索引（功能需求 FR1）。

**本模块在一期已降级为「原语层」**：不再承担 vault 级别的编排（对账、护栏、dry_run、
进度、取消），那些全部上移到 `sync_service`（对账层）与 `run_service`（作业层）。

三层职责（不可越界，见 M03 §5.6）：
    作业层 run_service      何时跑、跑到哪了、能不能停
    对账层 sync_service     要动哪些文件、允不允许删
    原语层 ingest_service   单个文件怎么进 / 出索引     ← 本模块

能力：
- 单文件管道：路由解析器（app/parsers/*）→ 分块（chunker）→ 嵌入（embedder）
  → 写向量库（vectorstore）→ 写元数据（note_repo）
- 文件级替换语义：索引前先清掉该文件的旧分块行与旧向量
- **embedding 模型绑定**：写入 chunks.embed_profile_id；向量落在
  collection_name(vault_id, profile_id)（见 M08 §2）

主要函数（全部是文件级原语，供 sync_service 与 doctor 复用）：
- async def index_file(vault, local_path, rel_path, embed_runtime) -> int
      索引单个文件，返回分块数。**实现即「文件级替换」**：先 drop_file 清旧 chunks 行
      与旧向量，再解析 → 分块 → 嵌入 → 写入。
      **不可**改成「按 chunk_idx upsert」—— 文件变短时会留下幽灵向量（M03 ADR-8），
      那是检索会召回已删除内容的最高危 bug。
- async def drop_file(vault, note_id) -> None
      删除某文件的 chunks 行与对应向量（文件被删除 / 被过滤规则移出范围时用）。
- async def move_file(vault, note_id, new_rel_path) -> None
      内容未变、仅路径变化：只更新 notes.file_path 与 Chroma 的 metadatas.file_path。
      不重新分块、不重新 embedding —— 同一文本 + 同一模型的向量在数学上完全等价。

单文件管道的完整规格（解析器路由 / 分块参数 / 失败重试 / 空文件处理）见 M03 §5.2–§5.5。

关联方案：M03 §4.1（数据流）/ §5.6（三层职责）/ §5.8–§5.12（变更管理，本模块是被调用方）；
         docs/design.md §16（多格式与过滤）、§18（多模型）。
"""
from pathlib import Path

from app.models.orm import Vault
from app.models.schemas import ModelRuntime


async def index_file(vault: Vault, local_path: Path, rel_path: str,
                     embed_runtime: "ModelRuntime | None" = None) -> int:
    """索引单个文件，返回分块数。实现 = 文件级替换（先 drop_file 再写新的）。"""
    ...


async def drop_file(vault: Vault, note_id: int) -> None:
    """删除某文件的 chunks 行与对应向量（文件被删除 / 被过滤规则移出索引范围时用）。"""
    ...


async def move_file(vault: Vault, note_id: int, new_rel_path: str) -> None:
    """内容未变、仅路径变化：只更新 notes.file_path 与 Chroma metadatas.file_path。

    不重新分块、不重新 embedding（同一文本 + 同一模型的向量在数学上完全等价）。
    """
    ...
