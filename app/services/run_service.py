"""业务·作业层 — 索引类操作的异步作业生命周期（M03 §5.13）。

三层边界（互不越界，见 M03 §5.6）：
    作业层（本模块）          何时跑、跑到哪了、能不能停
    对账层（sync_service）    要动哪些文件、允不允许删
    原语层（ingest_service）  单个文件怎么进 / 出索引

为什么全异步，而不是同步返回或 `wait` 参数（M03 ADR-12）：
  - 全量 rebuild 需 2–10 min（嵌入是瓶颈），同步返回必撞网关 60s 超时
  - 客户端断连时 asyncio 任务**不会**被取消，它会继续跑、继续烧 embedding，
    却没人接收结果 ——「活干了、钱花了、不知道结果」
  - 同步方案若要支持「断连后继续」，就得引入 wait_for + shield
    （漏 shield 即「超时静默取消任务」这种极难排查的 bug），
    而这种复杂度在纯异步下**根本不存在**：先落库(queued) → create_task → 返回 202 + run_id，
    两条生命周期彻底解耦，无需 shield、没有取消语义的坑

能力：
- submit()         抢锁 → 落库(queued) → create_task → 返回 SyncRun（调用方随即回 202）
- execute()        后台协程本体：推进 stage、节流上报进度、文件边界检查取消、收尾写终态
- request_cancel() 置 cancel_requested（协作式，文件边界生效，M03 ADR-14）
- recover_stale()  启动清理：残留 running → aborted（不做断点续跑，sync 本身幂等）
- ProgressReporter 进度上报：时间节流 + 阶段跳变必写 + 终态强制写（M03 ADR-13）

主要函数：
- async def submit(vault, mode="sync", dry_run=False, prune=True, force=False,
                   filters=None, embed_profile=None, trigger="manual") -> SyncRun
      抢不到 vault 锁 → 抛 AlreadyRunning(existing_run_id)，由 API 层转 409（M06 ADR-8）
- async def execute(run_id: int) -> None
      后台协程。收尾时写终态与计数；**作业成功时**才回写 vault 的
      embed_profile_id / embed_indexed_profiles（M06 ADR-9）
- async def request_cancel(run_id: int) -> bool
      返回是否成功（作业已终态 → False → API 层 409）
- async def recover_stale(session) -> int
      启动钩子调用；全部残留 running → aborted

**关键约束（做错会留下极难排查的 bug）**：
1. 必须先落库（queued）**再** create_task。反过来的话，进程若在「返回 run_id」与
   「建 task」之间崩溃，客户端就拿到一个永远查不到的 run_id（M03 §5.13.2）。
2. 进度写库失败只记 WARNING —— 进度是**观测信息**，不是正确性依赖，
   绝不能让它把整次索引判失败（ADR-13）。
3. 取消只检查**文件边界**，不进分块中途 —— 文件级替换是幂等单元，
   停在文件边界天然一致（ADR-14）。
4. 作业失败 / 取消时，vault 的模型状态**保持原值**，绝不写入未生效的模型（M06 ADR-9）。

关联方案：M03 §5.13 + ADR-12 / ADR-13 / ADR-14；M06 §5.3 + ADR-8 / ADR-9；
         M07 §5.4（前端进度视图的契约来源）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.models.orm import Vault
from app.models.schemas import IngestFilters, ModelRuntime

logger = logging.getLogger(__name__)

# vault 级互斥锁：key = vault_id。**单进程内有效** —— 一期按单 worker 部署（M10 明示）。
# 多副本时改用 sync_runs 行锁 + 文件锁（列入 M03 §12 未决）。
_vault_locks: dict[int, asyncio.Lock] = {}

# 进度落库的最小间隔（M03 ADR-13）。阶段跳变与终态不受此限。
PROGRESS_FLUSH_MS = 500


class AlreadyRunning(Exception):
    """同 vault 已有作业在跑。

    API 层据此返回 `409 Conflict` + `existing_run_id`，让调用方直接跳到
    那个任务的进度视图，而不是收到一个静默失效的请求（M06 ADR-8）。
    """

    def __init__(self, existing_run_id: int, status: str = "running") -> None:
        self.existing_run_id = existing_run_id
        self.status = status
        super().__init__(f"vault already has an active run: {existing_run_id}")


class ProgressReporter:
    """进度上报器：内存累加 + 时间节流落库（M03 §5.13.4）。

    节流策略（三档，缺一不可）：
      1. 时间节流 —— 距上次落库 ≥ flush_ms 才写，期间进度只累加在内存
      2. 阶段跳变必写 —— stage 变化一律立即写（前端状态机的转换点）
      3. 终态强制写 —— 收尾时无条件写，否则最后一段进度会丢

    这段是**纯技术节流**（无业务语义），可直接使用；要调整粒度改 PROGRESS_FLUSH_MS 即可。
    """

    def __init__(self, run_id: int, flush_ms: int = PROGRESS_FLUSH_MS) -> None:
        self.run_id = run_id
        self.flush_ms = flush_ms
        self.stage: str = "queued"
        self.total: Optional[int] = None
        self.processed: int = 0
        self.current_item: Optional[str] = None
        self.message: Optional[str] = None
        self._last_flush: float = 0.0

    async def advance(self, stage: str, total: Optional[int] = None) -> None:
        """切换阶段并**立即**落库（阶段跳变必写）。

        total 传 None 表示该阶段总量不可知（如 scan）——前端据此转「不确定态」进度条，
        不能硬编一个假分母（M03 §5.13.3）。
        """
        self.stage = stage
        self.total = total
        self.processed = 0
        self.current_item = None
        await self.flush(force=True)

    async def tick(self, item: Optional[str] = None, message: Optional[str] = None) -> None:
        """推进一个单位（通常是「处理完一个文件」）。是否真落库由节流决定。"""
        self.processed += 1
        self.current_item = item
        if message is not None:
            self.message = message
        await self.flush(force=False)

    async def flush(self, force: bool = False) -> None:
        """落库。写入失败只记 WARNING —— 进度不是正确性依赖（ADR-13）。"""
        now = time.monotonic() * 1000
        if not force and (now - self._last_flush) < self.flush_ms:
            return
        self._last_flush = now
        try:
            from app.core.database import session_scope  # 局部引入，避免循环依赖
            from app.repositories import sync_repo

            async with session_scope() as session:
                await sync_repo.update_progress(
                    session,
                    run_id=self.run_id,
                    stage=self.stage,
                    total=self.total,
                    processed=self.processed,
                    current_item=self.current_item,
                    message=self.message,
                )
        except Exception:  # noqa: BLE001 —— 进度失败绝不冒泡（ADR-13）
            logger.warning("进度落库失败（忽略，不影响索引）: run_id=%s", self.run_id, exc_info=True)

    def cancel_requested(self) -> bool:
        """当前是否已收到取消请求。由执行循环在**文件边界**调用（ADR-14）。

        实现提示：读 DB 的 cancel_requested 列（可能在别处被 API 改写），
        或维护一个进程内标志位并在 request_cancel() 里置位。
        """
        ...


async def submit(
    vault: Vault,
    mode: str = "sync",
    dry_run: bool = False,
    prune: bool = True,
    force: bool = False,
    filters: Optional[IngestFilters] = None,
    embed_runtime: Optional[ModelRuntime] = None,
    trigger: str = "manual",
):
    """提交一个作业（M03 §5.13.2）。

    顺序**不可调换**：
      1. 抢 vault 锁 —— 失败说明已有作业在跑 → 查它的 run_id 并抛 AlreadyRunning（API 转 409）
      2. create_sync_run(...) 落库，status="queued"、stage="queued"
      3. asyncio.create_task(execute(run_id)) —— 任务生命周期从此刻开始
      4. 返回 SyncRun；调用方随即回 202 + run_id，HTTP 请求生命周期在此结束

    第 2 步必须在第 3 步之前：否则进程若在「返回 run_id」与「建 task」之间崩溃，
    客户端会拿到一个永远查不到的 run_id。

    lock = _vault_locks.setdefault(vault.id, asyncio.Lock())
    ...
    """
    ...


async def execute(run_id: int) -> None:
    """后台协程本体：从 queued 一路推进到终态。

    阶段序列（与 M03 §5.13.3 的进度表一一对应）：
      queued → probe → scan → diff → plan [→ plan_ready] → index → prune → done

    要点：
    - 用 ProgressReporter 上报进度；scan 阶段 total=None（不可知）
    - 每个文件处理完调用一次「取消检查」（文件边界，ADR-14）；
      命中则停在当前边界、status="cancelled"、已完成文件保留
    - dry_run 作业在 plan_ready 收尾（不进入 index / prune），并**立即释放锁**
    - 收尾：finish_sync_run(...) 写 status + 计数 + detail_json；
      **仅当 status in (success, partial)** 才回写 vault 的
      embed_profile_id / embed_indexed_profiles（M06 ADR-9）
    - 全程 finally 释放 vault 锁，确保异常也不会把锁永久占住

    实现时把对账与执行委托给 sync_service.sync_vault(..., progress=reporter)，
    本函数只负责「生命周期 + 进度 + 取消 + 收尾」，不重复实现对账逻辑（§5.6）。
    """
    ...


async def request_cancel(run_id: int) -> bool:
    """请求取消：置 cancel_requested = True，返回是否受理（M03 §5.13.5）。

    返回 False 表示作业已是终态（success / partial / failed / cancelled / aborted），
    API 层据此返回 409。
    注意：本函数**只是置标志**，任务不会立刻停止 —— 它在下一个文件边界才停（ADR-14），
    此前前端应显示 cancelling=true（「正在停止…」）。
    """
    ...


async def recover_stale(session) -> int:
    """启动清理：把残留的 status='running' / 'queued' 全部置为 aborted（M03 §5.13.6）。

    为什么这么做：create_task 的任务随进程重启消失，不做断点续跑
    （sync 本身幂等，重跑一次比持久化中间态简单得多）。
    不清理的话，用户会看到一条永远 running 的僵尸作业，且「是否有作业在跑」的判断被阻塞。

    返回被标记的行数；由 main.py 的启动钩子调用。
    """
    ...


async def run_scheduled_sync(interval_seconds: int) -> None:
    """定时同步循环（INGEST_SYNC_INTERVAL > 0 时由启动钩子创建）。

    对全部 vault 依次 submit 增量作业；抢不到锁（已有作业在跑）则**静默跳过、不排队**，
    记日志即可（trigger="schedule"）。
    """
    ...
