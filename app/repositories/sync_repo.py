"""数据访问·作业记录 — sync_runs 表的读写（作业表 + 可观测载体，M03 §5.11 / §5.13）。

能力：
- 作业生命周期：create（queued）→ mark_running（拿到执行槽后）→ update_progress（节流）→ finish（终态 + 计数）
- 查询：按 vault 列历史、按 run_id 取详情、判定「是否已有作业在跑」
- 取消：置 cancel_requested（协作式；本层只置标志，执行侧在文件边界才生效）
- 裁剪：每 vault 保留最近 N 条（SYNC_RUNS_KEEP，默认 50），防定时同步撑爆表
- 启动清理：把崩溃残留的 queued / running 全部置为 aborted

主要函数：
- create_sync_run(session, vault_id, trigger, mode, dry_run, user_id) -> SyncRun
- get_sync_run(session, run_id, user_id=None) -> SyncRun | None
- find_active_run(session, vault_id) -> SyncRun | None
- mark_running(session, run_id) -> None
- update_progress(session, run_id, stage, total, processed, current_item, message) -> None
- finish_sync_run(session, run_id, status, counters, blocked_reason, error, detail_json) -> None
- request_cancel(session, run_id) -> bool
- list_sync_runs(session, vault_id, limit) -> list[SyncRun]
- trim_sync_runs(session, vault_id, keep) -> None
- recover_stale_runs(session) -> int

**返回值约定**：status 取值域见 orm.SyncRun 的 docstring（七态）。
写进度与收尾都应能容忍「行已被裁剪 / 不存在」的情况（记录被 trim 掉不应报错）。
all 函数都不 commit —— 事务边界由调用方（service / 路由）决定。

关联方案：M03 §5.11 / §5.13；M06 ADR-7（记录落库）、ADR-8（409 判定依据）。
"""
import json
from datetime import datetime, timezone

from sqlalchemy import select, delete as sa_delete, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SyncRun

_ACTIVE_STATUSES = ("queued", "running")


async def create_sync_run(
    session: AsyncSession,
    vault_id: int,
    trigger: str = "manual",
    mode: str = "sync",
    dry_run: bool = False,
    user_id: str = "default",
) -> SyncRun:
    """新建作业记录：status="queued"、stage="queued"，返回该 SyncRun。

    **必须在 asyncio.create_task 之前提交**（M03 §5.13.2）。
    """
    run = SyncRun(
        vault_id=vault_id,
        user_id=user_id,
        trigger=trigger,
        mode=mode,
        dry_run=dry_run,
        status="queued",
        stage="queued",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_sync_run(
    session: AsyncSession, run_id: int, user_id: str | None = None
) -> SyncRun | None:
    """取单个作业详情（进度轮询用）。带 user_id 时同时校验归属。"""
    query = select(SyncRun).where(SyncRun.id == run_id)
    if user_id is not None:
        query = query.where(SyncRun.user_id == user_id)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def find_active_run(session: AsyncSession, vault_id: int) -> SyncRun | None:
    """取该 vault 当前进行中的作业（status in queued / running）。"""
    result = await session.execute(
        select(SyncRun).where(
            SyncRun.vault_id == vault_id,
            SyncRun.status.in_(_ACTIVE_STATUSES),
        ).order_by(SyncRun.id.desc())
    )
    return result.scalar_one_or_none()


async def mark_running(session: AsyncSession, run_id: int) -> None:
    """queued → running：作业**拿到全局执行槽、真正开始执行**时调用。

    排队等槽期间保持 queued —— 那才是「排队」的准确语义（前端 KPI 靠它区分
    「执行中」与「排队」，不写这一笔的话所有作业会一直显示排队中）。
    只改仍为 queued 的行，避免覆盖已被取消 / 裁剪的记录。
    """
    await session.execute(
        sa_update(SyncRun)
        .where(SyncRun.id == run_id, SyncRun.status == "queued")
        .values(status="running")
    )
    await session.commit()


async def update_progress(
    session: AsyncSession,
    run_id: int,
    stage: str,
    total: int | None,
    processed: int,
    current_item: str | None,
    message: str | None,
) -> None:
    """更新进度列（由 run_service.ProgressReporter 节流后调用）。

    `total=None` 表示该阶段总量不可知（scan 阶段）。
    行已被裁剪时不报错（进度不是正确性依赖）。
    """
    await session.execute(
        sa_update(SyncRun)
        .where(SyncRun.id == run_id)
        .values(
            stage=stage,
            total=total,
            processed=processed,
            current_item=current_item,
            message=message,
        )
    )
    await session.commit()


async def finish_sync_run(
    session: AsyncSession,
    run_id: int,
    status: str,
    counters: dict,
    blocked_reason: str | None = None,
    error: str | None = None,
    detail_json: str = "{}",
) -> None:
    """收尾：写终态 / 计数 / 护栏原因 / 失败清单 / finished_at / elapsed_ms。

    counters 形如 {adds, updates, moves, deletes, unchanged, failed_cnt, embed_profile_id}。
    status 取值：success | partial | failed | cancelled | aborted。
    行已被裁剪时不报错。
    """
    now = datetime.now(timezone.utc)

    # 先取 started_at 计算 elapsed_ms
    result = await session.execute(
        select(SyncRun.started_at).where(SyncRun.id == run_id)
    )
    started_at = result.scalar_one_or_none()
    elapsed_ms = 0
    if started_at is not None:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        elapsed_ms = int((now - started_at).total_seconds() * 1000)

    values = {
        "status": status,
        "stage": "done",
        "finished_at": now,
        "elapsed_ms": elapsed_ms,
        "blocked_reason": blocked_reason,
        "error": error,
        "detail_json": detail_json if isinstance(detail_json, str) else json.dumps(detail_json),
    }
    # 展开 counters 到独立列
    for key in ("adds", "updates", "moves", "deletes", "unchanged", "failed_cnt"):
        if key in counters:
            values[key] = counters[key]
    if "embed_profile_id" in counters:
        values["embed_profile_id"] = counters["embed_profile_id"]
    # processed 对齐 total
    if "total" in counters:
        values["total"] = counters["total"]
        values["processed"] = counters["total"]

    await session.execute(
        sa_update(SyncRun).where(SyncRun.id == run_id).values(**values)
    )
    await session.commit()


async def request_cancel(session: AsyncSession, run_id: int) -> bool:
    """置 cancel_requested = True，返回是否受理。

    返回 False = 作业已是终态（不可取消）。重复取消无副作用（幂等）。
    """
    result = await session.execute(
        select(SyncRun.status).where(SyncRun.id == run_id)
    )
    status = result.scalar_one_or_none()
    if status is None or status not in _ACTIVE_STATUSES:
        return False

    await session.execute(
        sa_update(SyncRun)
        .where(SyncRun.id == run_id)
        .values(cancel_requested=True)
    )
    await session.commit()
    return True


async def list_sync_runs(
    session: AsyncSession, vault_id: int, limit: int = 20
) -> list[SyncRun]:
    """按 vault 取最近 limit 条作业记录，按 started_at 倒序。"""
    result = await session.execute(
        select(SyncRun)
        .where(SyncRun.vault_id == vault_id)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def trim_sync_runs(
    session: AsyncSession, vault_id: int, keep: int = 50
) -> None:
    """只保留最近 keep 条，其余按时间删除。**不得**删掉 queued / running 的行。"""
    # 取要保留的 id 列表（最近 keep 条 + 所有 active）
    keep_result = await session.execute(
        select(SyncRun.id)
        .where(SyncRun.vault_id == vault_id)
        .order_by(SyncRun.started_at.desc())
        .limit(keep)
    )
    keep_ids = set(keep_result.scalars().all())

    active_result = await session.execute(
        select(SyncRun.id).where(
            SyncRun.vault_id == vault_id,
            SyncRun.status.in_(_ACTIVE_STATUSES),
        )
    )
    keep_ids.update(active_result.scalars().all())

    if not keep_ids:
        return

    await session.execute(
        sa_delete(SyncRun).where(
            SyncRun.vault_id == vault_id,
            SyncRun.id.notin_(keep_ids),
        )
    )
    await session.commit()


async def recover_stale_runs(session: AsyncSession) -> int:
    """启动清理：把全部残留 queued / running 置为 aborted，返回被标记行数。

    不限于单个 vault —— 进程重启后内存中的 task 全部消失。
    """
    result = await session.execute(
        sa_update(SyncRun)
        .where(SyncRun.status.in_(_ACTIVE_STATUSES))
        .values(status="aborted", stage="done")
    )
    await session.commit()
    return result.rowcount
