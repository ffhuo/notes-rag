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
- submit()         抢 vault 锁 → 落库(queued) → create_task → 返回 SyncRun（调用方随即回 202）
- execute()        后台协程本体：推进 stage、节流上报进度、文件边界检查取消、收尾写终态
- request_cancel() 置 cancel_requested（协作式，文件边界生效，M03 ADR-14）
- recover_stale()  启动清理：残留 running → aborted（不做断点续跑，sync 本身幂等）
- ProgressReporter 进度上报：时间节流 + 阶段跳变必写 + 终态强制写（M03 ADR-13）

并发语义（两层，勿混）：
- 同一 vault：_vault_locks 互斥，第二个提交**立即 409，不排队**
- 不同 vault：各自提交都成功并建 task，但执行前要抢**全局执行槽**
  _global_slots（Semaphore，容量 INGEST_MAX_CONCURRENCY，默认 1）——
  即 N 个 vault 同时提交也严格**串行执行**，拿不到槽的任务停在 queued 排队；
  排队期间可被取消（_acquire_slot 轮询响应 cancel_requested）。

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
5. 作业与 API 同处一个进程 —— **绝不阻塞事件循环**（M03 §5.13.8）：
   - 同步客户端（chromadb / requests / 同步 SDK）一律 `asyncio.to_thread(...)` 包裹；
   - embedding 并发用 Semaphore 封顶，别与 /search、/chat 抢供应商 RPM；
   - 紧密同步循环每 N 个文件 `await asyncio.sleep(0)` 让出一次。
   违反的后果不是作业慢，而是**全站接口一起卡死**。

关联方案：M03 §5.13 + ADR-12 / ADR-13 / ADR-14；M06 §5.3 + ADR-8 / ADR-9；
         M07 §5.4（前端进度视图的契约来源）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from app.core.config import settings
from app.core.database import session_scope
from app.models import Vault
from app.models.schemas import IngestFilters, ModelRuntime
from app.repositories import sync_repo, vault_repo
from app.services import model_service
from app.services.model_service import to_runtime

logger = logging.getLogger(__name__)

# vault 级互斥锁：key = vault_id。**单进程内有效** —— 一期按单 worker 部署（M10 明示）。
# 多副本时改用 sync_runs 行锁 + 文件锁（列入 M03 §12 未决）。
_vault_locks: dict[int, asyncio.Lock] = {}

# 协作式取消的进程内标志（run_id 集合）。单 worker 内 API 与后台作业同进程，
# 故同步可读；DB 列 sync_runs.cancel_requested 负责持久化与展示。
_cancel_flags: set[int] = set()

# 全局执行槽：跨 vault 串行化「实际执行」。与 _vault_locks 分工——
#   _vault_locks 管「同一 vault 不并发」（冲突立即 409，不排队）；
#   _global_slots 管「不同 vault 同时只跑 N 个」（拿不到就排队等待，不拒绝）。
# 默认 INGEST_MAX_CONCURRENCY=1 → 多个 vault 同时提交也严格一个跑完再跑下一个，
# 避免 N 个 rebuild 叠加 embedding 请求撞供应商 RPM、争抢 Chroma 写线程。
# 下限钳为 1：Semaphore(0) 会永久阻塞。
_global_slots = asyncio.Semaphore(max(1, settings.ingest_max_concurrency))

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
        """当前是否已收到取消请求。由执行循环在**文件边界**同步调用（ADR-14）。

        标志用进程内集合（单 worker 部署，API 与作业同进程）；同时已持久化到
        sync_runs.cancel_requested 供可观测 / 重启恢复。execute 启动时会用 DB 值
        为该集合播种，覆盖「重启前已点取消」的边界。
        """
        return self.run_id in _cancel_flags


async def submit(
    vault: Vault,
    mode: str = "sync",
    dry_run: bool = False,
    prune: bool = True,
    force: bool = False,
    filters: Optional[IngestFilters] = None,
    embed_runtime: Optional[ModelRuntime] = None,
    embed_profile_id: "int | str | None" = None,
    trigger: str = "manual",
    user_id: Optional[str] = None,
):
    """提交一个作业（M03 §5.13.2）。

    顺序**不可调换**：
      1. 抢 vault 锁 —— 失败说明已有作业在跑 → 查它的 run_id 并抛 AlreadyRunning（API 转 409）
      2. create_sync_run(...) 落库，status="queued"、stage="queued"
      3. asyncio.create_task(execute(...)) —— 任务生命周期从此刻开始（锁由 execute 持有到收尾）
      4. 返回 SyncRun；调用方随即回 202 + run_id，HTTP 请求生命周期在此结束

    第 2 步必须在第 3 步之前：否则进程若在「返回 run_id」与「建 task」之间崩溃，
    客户端会拿到一个永远查不到的 run_id。
    """
    lock = _vault_locks.setdefault(vault.id, asyncio.Lock())

    # 抢锁：已被占 → 查 DB 里进行中的作业，带 run_id 抛 409
    if lock.locked():
        existing_id: Optional[int] = None
        async with session_scope() as session:
            active = await sync_repo.find_active_run(session, vault.id)
            if active is not None:
                existing_id = active.id
        raise AlreadyRunning(existing_id or -1)

    # 获取锁：上面 locked() 已挡，且无竞争时 Lock.acquire 的快速路径不让出事件循环，
    # 故此处必然立即成功（不存在「检查与获取之间被别人抢走」的窗口）。
    # 注意：asyncio.Lock **没有** acquire_nowait（也没有 asyncio.WouldBlock），别再用它兜底。
    await lock.acquire()

    try:
        async with session_scope() as session:
            run = await sync_repo.create_sync_run(
                session,
                vault_id=vault.id,
                trigger=trigger,
                mode=mode,
                dry_run=dry_run,
                user_id=user_id or vault.user_id,
            )
            run_id = run.id
    except Exception:
        lock.release()
        raise

    # 先落库、后建任务（ADR 关键约束）。锁在 _run_guarded 的 finally 释放。
    asyncio.create_task(
        _run_guarded(
            lock,
            run_id,
            embed_runtime=embed_runtime,
            embed_profile_id=embed_profile_id,
            prune=prune,
            force=force,
            filters=filters,
        )
    )
    logger.info("作业已提交 run_id=%s vault=%s mode=%s trigger=%s", run_id, vault.id, mode, trigger)
    return run


async def _run_guarded(lock: asyncio.Lock, run_id: int, **kwargs) -> None:
    """execute 的外壳。

    顺序：先排队拿全局执行槽（跨 vault 串行），拿到后才真正执行；
    无论成功 / 失败 / 取消 / 排队中取消，都在 finally 释放本 vault 锁。
    """
    try:
        got_slot = await _acquire_slot(run_id)
        if not got_slot:
            # 排队期间被取消：不进入 execute，直接落终态（status 仍停在 queued）
            await _finish(run_id, "cancelled", {})
            logger.info("作业在排队等待执行槽时被取消 run_id=%s", run_id)
            return
        try:
            await execute(run_id, **kwargs)
        finally:
            _global_slots.release()
    finally:
        lock.release()
        _cancel_flags.discard(run_id)


async def _acquire_slot(run_id: int, poll_s: float = 0.5) -> bool:
    """排队等待全局执行槽；等待期间每 poll_s 检查一次取消。

    返回 True=已拿到槽（调用方负责 release）；False=排队期间被取消（未拿槽）。
    不能直接 `await sem.acquire()`：那会无视取消，让一个 queued 作业等到前面
    数分钟的 rebuild 跑完才被处理。
    """
    while True:
        if run_id in _cancel_flags:
            return False
        try:
            await asyncio.wait_for(_global_slots.acquire(), timeout=poll_s)
            # 等待结束的瞬间也要复核取消：若取消与拿槽同时发生，让位并退出
            if run_id in _cancel_flags:
                _global_slots.release()
                return False
            return True
        except asyncio.TimeoutError:
            continue


async def execute(
    run_id: int,
    embed_runtime: Optional[ModelRuntime] = None,
    embed_profile_id: "int | str | None" = None,
    prune: bool = True,
    force: bool = False,
    filters: Optional[IngestFilters] = None,
) -> None:
    """后台协程本体：从 queued 一路推进到终态。

    阶段由 sync_service 内部驱动（scan total=None → index 有确定 total）；
    本函数只负责生命周期、进度、取消、收尾与 vault 模型状态回写（§5.6 分层）。
    """
    from app.services import sync_service, vault_service  # 局部引入，避免与 vault_service 循环依赖

    reporter = ProgressReporter(run_id)

    async with session_scope() as session:
        run = await sync_repo.get_sync_run(session, run_id)
    if run is None:
        logger.error("execute 找不到作业记录 run_id=%s", run_id)
        return

    # 重启前已点取消（stale 通常已 aborted；此处双保险）
    if run.cancel_requested:
        _cancel_flags.add(run_id)

    async with session_scope() as session:
        vault = await vault_repo.get_vault(session, run.vault_id, run.user_id)
    if vault is None:
        await _finish(run_id, "failed", {}, error="vault 不存在")
        return

    # 正式执行：queued → running。排队等全局执行槽期间保持 queued，
    # 前端 KPI 才能把「执行中」与「排队」分开（此前从不写 running，两者混为一谈）。
    async with session_scope() as session:
        await sync_repo.mark_running(session, run_id)

    # dry_run / 计划标志位取自 DB 行（它们在落库时已确定）
    try:
        local_path = vault_service.resolve_local_path(vault, settings)
    except vault_service.SourceUnavailable as e:
        await reporter.advance("probe", None)
        await _finish(run_id, "failed", {}, blocked_reason="source_unavailable", error=str(e))
        return

    # 解析 embedding 运行时：submit 已带则复用；否则按 vault 当前 profile 解析
    # （正常路径 submit 已把关，无 embed 配置时进不到这里；这里只兜住历史 / 手工调用）
    runtime, resolved_profile_id = embed_runtime, embed_profile_id
    if runtime is None:
        async with session_scope() as session:
            ref = str(resolved_profile_id or vault.embed_profile_id) if (
                resolved_profile_id or vault.embed_profile_id
            ) else None
            profile = await model_service.resolve_profile(
                session, "embed", ref=ref, user_id=vault.user_id
            )
            runtime = to_runtime(profile)
            resolved_profile_id = profile.id

    # 解析图片处理用的多模态 LLM 运行时（本层解析一次，与 embed 同模式下传整个作业）。
    # 无多模态配置时返回 None —— 图片处理整段跳过，绝不让文件索引失败。
    async with session_scope() as session:
        image_runtime = await model_service.resolve_image_runtime(session, vault.user_id)
    if image_runtime is not None:
        logger.info("启用图片处理 model=%s vault_id=%s", image_runtime.model, vault.id)

    effective_filters = filters or _vault_filters(vault)

    # 阶段由 sync_service 驱动（probe → scan → diff → index）；本层不写自己的阶段名，
    # 否则前端会拿到没有中文标签的伪阶段
    try:
        result = await sync_service.sync_vault(
            vault,
            local_path,
            mode=run.mode,
            dry_run=run.dry_run,
            prune=prune,
            force=force,
            filters=effective_filters,
            embed_runtime=runtime,
            embed_profile_id=resolved_profile_id,
            image_runtime=image_runtime,
            progress=reporter,
        )
    except Exception as e:  # noqa: BLE001 —— 任何未预期异常都要落终态，不能留僵尸作业
        logger.exception("作业异常 run_id=%s", run_id)
        await reporter.flush(force=True)
        await _finish(run_id, "failed", {}, error=str(e))
        return

    # 终态判定
    if result.skipped_reason == "cancelled":
        status = "cancelled"
    elif result.blocked_reason == "source_unavailable":
        status = "failed"
    elif result.failed > 0:
        status = "partial"
    else:
        status = "success"

    counters = {
        "adds": result.adds,
        "updates": result.updates,
        "moves": result.moves,
        "deletes": result.deletes,
        "unchanged": result.unchanged,
        "failed_cnt": result.failed,
        "embed_profile_id": resolved_profile_id if isinstance(resolved_profile_id, int) else None,
    }
    detail = {
        "failed_files": result.failed_files,
        "samples": result.samples,
        "skipped_reason": result.skipped_reason,
    }

    await reporter.flush(force=True)
    await _finish(
        run_id, status, counters,
        blocked_reason=result.blocked_reason,
        error=result.skipped_reason if status == "failed" else None,
        detail_json=json.dumps(detail, ensure_ascii=False),
    )

    # 仅成功 / 部分成功且非 dry_run 才回写 vault 模型状态（ADR-9）
    if status in ("success", "partial") and not run.dry_run:
        await _writeback_vault_model(vault, resolved_profile_id)

    # 裁剪历史
    async with session_scope() as session:
        await sync_repo.trim_sync_runs(session, vault.id, keep=settings.sync_runs_keep)


async def _finish(run_id, status, counters, *, blocked_reason=None, error=None, detail_json="{}"):
    async with session_scope() as session:
        await sync_repo.finish_sync_run(
            session, run_id, status, counters,
            blocked_reason=blocked_reason, error=error, detail_json=detail_json,
        )


def _vault_filters(vault: Vault) -> Optional[IngestFilters]:
    """从 vault.filters_json 还原摄取过滤；无 / 非法 → None（用 settings 默认）。"""
    try:
        raw = json.loads(vault.filters_json or "{}")
        if not raw:
            return None
        return IngestFilters.model_validate(raw)
    except (ValueError, TypeError):
        return None


async def _writeback_vault_model(vault: Vault, profile_id) -> None:
    """作业成功后回写 vault 模型状态（ADR-9）。失败 / 取消不调用本函数。

    仅做编排：读改写与 commit 全部在 vault_repo.touch_embed_state；
    env 占位（非 int）传 None → 只刷新 indexed_at。
    """
    try:
        async with session_scope() as session:
            ok = await vault_repo.touch_embed_state(
                session,
                vault.id,
                vault.user_id,
                profile_id if isinstance(profile_id, int) else None,
            )
        if not ok:
            logger.warning("vault 模型状态回写跳过：vault 不存在 vault=%s", vault.id)
    except Exception:  # noqa: BLE001 —— 状态回写失败不改变作业已成功的事实
        logger.warning("vault 模型状态回写失败 vault=%s", vault.id, exc_info=True)


async def request_cancel(run_id: int) -> bool:
    """请求取消：置 cancel_requested = True，返回是否受理（M03 §5.13.5）。

    返回 False 表示作业已是终态（success / partial / failed / cancelled / aborted），
    API 层据此返回 409。本函数**只是置标志**，任务在下一个文件边界才停（ADR-14）。
    """
    async with session_scope() as session:
        accepted = await sync_repo.request_cancel(session, run_id)
    if accepted:
        _cancel_flags.add(run_id)
    return accepted


async def recover_stale(session) -> int:
    """启动清理：把残留的 status='running' / 'queued' 全部置为 aborted（M03 §5.13.6）。

    create_task 的任务随进程重启消失，不做断点续跑（sync 本身幂等）。
    返回被标记的行数；由 main.py 的启动钩子调用。
    """
    _cancel_flags.clear()
    return await sync_repo.recover_stale_runs(session)


async def run_scheduled_sync(interval_seconds: int) -> None:
    """定时同步循环：每 interval 秒对全部 vault 依次 submit 增量作业。

    抢不到锁（已有作业在跑）则静默跳过、不排队（trigger="schedule"）。
    """
    if interval_seconds <= 0:
        return
    logger.info("定时同步循环启动 interval=%ss", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with session_scope() as session:
                vaults = await vault_repo.list_all_vaults(session)
            for vault in vaults:
                try:
                    await submit(vault, mode="sync", trigger="schedule")
                except AlreadyRunning:
                    logger.info("vault=%s 已有作业，定时触发跳过", vault.id)
                except Exception:  # noqa: BLE001 —— 单 vault 失败不影响后续与循环
                    logger.warning("vault=%s 定时同步提交失败", vault.id, exc_info=True)
        except asyncio.CancelledError:
            logger.info("定时同步循环停止")
            raise
        except Exception:  # noqa: BLE001
            logger.warning("定时同步轮询异常", exc_info=True)
