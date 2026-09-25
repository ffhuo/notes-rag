"""业务·变更管理 — vault 文件变化（新增 / 修改 / 删除 / 改名）的对账与同步。

能力：
- **两段式变更判据**：L1 = size_bytes + mtime_ns（遍历 stat 即得，零额外 IO，筛掉绝大多数未变文件）；
  L2 = content_hash（仅 L1 不一致时计算，识别「时间戳变了但内容没变」——
  否则一次 git checkout / rsync 会触发整库重新 embedding）
- **四类变更的对账**：新增 / 修改 / 移动（内容不变仅改名，零 embedding）/ 删除（含「移出过滤范围」）
- **删除三护栏**（本模块最重要的正确性约束，见 M03 ADR-7）：
    1. 源可达：不可达 → ABORT 整个 sync，绝不当成「内容全没了」
    2. 扫描完整：遍历有不可恢复错误 → 本轮只增不删
    3. 删除比例：len(to_remove)/len(known) > prune_ratio_limit（默认 0.5）→ 拒绝，需 force=true
- **dry_run**：只算不写，返回 SyncPlan，让用户先看「这次会动什么」
- 写 sync_runs 留痕（计数 / 护栏原因 / 失败文件清单）
- doctor：Chroma ↔ chunks ↔ 磁盘 三向一致性自检

主要函数：
- async def sync_vault(vault, local_path, mode="sync", dry_run=False, prune=True, force=False,
                       filters=None, embed_runtime=None, trigger="manual") -> SyncResult
      编排入口；`mode="rebuild"` 是本流程的特例（跳过对账，先 reset 再全量写），
      而不是另一套代码路径。
- def compute_file_sig(path) -> FileSig
      计算单文件判据（size_bytes / mtime_ns / content_hash）。
- def reconcile(signatures, known_notes, ratio_limit) -> tuple[ReconcilePlan, str | None]
      对账：分类四类变更 + 移动配对，并返回护栏判定结果（None = 允许删除）。
- async def doctor(vault, local_path, repair=False) -> DoctorReport
      三向自检与修复。

**边界（不可越界）**：本模块只决定「做什么」（对账 / 护栏 / dry_run），
「怎么做」（解析→分块→嵌入→写入）全部委托给 ingest_service 的文件级原语
（index_file / drop_file / move_file）—— 两条路径共用同一实现，防止行为漂移。

**与 run_service 的分工**（M03 §5.6）：
  - 本模块保持**同步语义**：调用 `sync_vault()` = 一直跑到结束才返回
  - 「何时跑、进度怎么写、能不能取消」全部由 run_service 负责，通过 `progress` 回调注入
  - 因此本模块**不 import run_service**，只依赖 `ProgressSink` 这一协议（下游可替换）
  - 定时同步循环也在 run_service（它同样要经作业提交与幂等/互斥逻辑）

关联方案：docs/design.md §4.1 / §5.1.1（数据流）。
变更管理完整方案见设计文档库 M03 §5.8–§5.12（判据四象限、替换写入、护栏阈值、sync_runs、doctor）。
"""
from pathlib import Path
from typing import Optional

from app.models.orm import Vault
from app.models.schemas import DoctorReport, IngestFilters, ModelRuntime, SyncResult


async def sync_vault(
    vault: Vault,
    local_path: Path,
    mode: str = "sync",
    dry_run: bool = False,
    prune: bool = True,
    force: bool = False,
    filters: "Optional[IngestFilters]" = None,
    embed_runtime: "ModelRuntime | None" = None,
    trigger: str = "manual",
    progress: "ProgressSink | None" = None,
) -> SyncResult:
    """对账并同步一个 vault 的索引。

    流程（M03 §4.2）：
      [0] 前置校验源可达（不可达 → ABORT）
      [1] 遍历 + 过滤 → seen = {相对路径: FileSig}（记录遍历错误，决定 scan_complete）
      [2] 对账 → to_add / to_check / to_remove / to_move
      [3] dry_run → 直接返回 SyncPlan
      [4] 删除三护栏 → 未通过则本轮只增不删（blocked_reason 写入结果与 sync_runs）
      [5] 执行：新增 / 修改（文件级替换：先删旧 chunks+向量再写新的）/ 移动（只改元数据）/ 删除
      [6] 写 sync_runs（计数 / 失败清单 / 耗时）

    进度与取消（由本函数驱动，但**状态存储归作业层**）：
      - 每个阶段开始时调 `progress.advance(stage, total)`；每处理完一个文件调
        `progress.tick(item, message)`；本函数不关心节流与落库（那是 run_service 的事）
      - **scan 阶段的 total 传 None**（文件总数遍历完才知道）→ 前端进度条转「不确定态」
      - 每个文件处理完毕后检查 `progress.cancel_requested()`；命中则停止取新文件、
        把已完成部分保留，返回 SyncResult 并让作业层记为 `cancelled`
      - 取消只发生在**文件边界**：文件级替换是幂等单元，停在边界天然一致（ADR-14）

    注意：`mode="rebuild"` 时跳过 [2] 的对账，先 reset collection 与旧行，再全量写。
    """
    ...


def compute_file_sig(path: Path) -> "FileSig":
    """计算单文件的变更判据。

    - size_bytes / mtime_ns：L1 快判据
    - content_hash：L2 权威判据，sha256(内容) 前 16 位 hex
      对**确定需要重索引**的文件，此处的读取应与解析合并（读一次字节流，既算 hash 又交给 parser）。
    """
    ...


def reconcile(signatures: dict, known_notes: dict, ratio_limit: float) -> tuple:
    """对账：把 seen 与 known 的差集分类为四类变更，并做移动配对与护栏判定。

    返回 (ReconcilePlan, blocked_reason)：
    - ReconcilePlan: { adds, updates, moves, deletes, unchanged, samples }
    - blocked_reason: None = 允许执行删除；否则为
      "source_unavailable" | "scan_incomplete" | "over_ratio" | "prune_disabled"

    移动配对规则（保守）：仅当 content_hash 在 to_remove 与 to_add 中**各自恰好出现一次**
    才配对；空文件 / 0 分块文件不参与配对；配对失败退化为「删除 + 新增」（正确性优先于成本）。
    """
    ...


async def doctor(vault: Vault, local_path: Path, repair: bool = False) -> DoctorReport:
    """三向一致性自检（M03 §5.12）。

    检测：幽灵向量（Chroma 有 / chunks 无）★ 最高危、缺失向量、孤儿笔记、模型错配。
    repair=True 时修复前两类（删幽灵 / 补缺失）；后两类只提示
    （孤儿交给 sync，模型错配交给 reindex）—— 修复策略刻意保守，不做复杂补偿事务。
    """
    ...

