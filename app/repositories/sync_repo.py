"""数据访问·作业记录 — sync_runs 表的读写（作业表 + 可观测载体，M03 §5.11 / §5.13）。

能力：
- 作业生命周期：create（queued）→ update_progress（节流）→ finish（终态 + 计数）
- 查询：按 vault 列历史、按 run_id 取详情、判定「是否已有作业在跑」
- 取消：置 cancel_requested（协作式；本层只置标志，执行侧在文件边界才生效）
- 裁剪：每 vault 保留最近 N 条（SYNC_RUNS_KEEP，默认 50），防定时同步撑爆表
- 启动清理：把崩溃残留的 queued / running 全部置为 aborted

为什么落在 DB 而不是只写日志：
「为什么这个文件没被索引」需要一个**面向用户**（前端可按 vault 查）的答案，
而日志面向开发者、会被轮转、无法按 vault 维度查询（见 M06 ADR-7）。

为什么进度也写这张表、不另建进度表：
进度字段与作业本身一对一、同生命周期，拆表只会多一次 join（M03 ADR-13）。

主要函数：
- create_sync_run(session, vault_id, trigger, mode, dry_run, user_id) -> SyncRun
- get_sync_run(session, run_id, user_id=None) -> SyncRun | None
- find_active_run(session, vault_id) -> SyncRun | None
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
from sqlalchemy.ext.asyncio import AsyncSession


async def create_sync_run(
    session: AsyncSession,
    vault_id: int,
    trigger: str = "manual",
    mode: str = "sync",
    dry_run: bool = False,
    user_id: str = "default",
):
    """新建作业记录：status="queued"、stage="queued"，返回该 SyncRun。

    **必须在 asyncio.create_task 之前提交**（M03 §5.13.2）—— 否则进程在
    「返回 run_id」与「建 task」之间崩溃时，客户端会拿到一个永远查不到的 run_id。
    """
    ...


async def get_sync_run(session: AsyncSession, run_id: int, user_id: str | None = None):
    """取单个作业详情（进度轮询用）。带 user_id 时同时校验归属（防越权）。"""
    ...


async def find_active_run(session: AsyncSession, vault_id: int):
    """取该 vault 当前进行中的作业（status in queued / running）。

    用途：submit 抢不到锁时查出 existing_run_id，供 API 返回 409（M06 ADR-8）。
    """
    ...


async def update_progress(
    session: AsyncSession,
    run_id: int,
    stage: str,
    total: int | None,
    processed: int,
    current_item: str | None,
    message: str | None,
) -> None:
    """更新进度列（由 run_service.ProgressReporter 节流后调用，M03 ADR-13）。

    `total=None` 表示该阶段总量不可知（scan 阶段）——不要替它编一个数字。
    本函数抛异常由调用方吞掉并记 WARNING（进度不是正确性依赖）。
    """
    ...


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
    同时把 stage 置 "done"、processed 对齐 total（前端进度条收满）。
    """
    ...


async def request_cancel(session: AsyncSession, run_id: int) -> bool:
    """置 cancel_requested = True，返回是否受理。

    返回 False = 作业已是终态（不可取消）→ API 层转 409。重复取消无副作用（幂等）。
    注意：置标志 ≠ 立刻停止，执行侧在**文件边界**才停（M03 ADR-14）。
    """
    ...


async def list_sync_runs(session: AsyncSession, vault_id: int, limit: int = 20) -> list:
    """按 vault 取最近 limit 条作业记录，按 started_at 倒序。

    前端「任务与进度」列表用（M07 §5.4）—— 需返回**全部状态**，
    由前端把运行中的置顶，而不是在 SQL 层过滤掉。
    """
    ...


async def trim_sync_runs(session: AsyncSession, vault_id: int, keep: int = 50) -> None:
    """只保留最近 keep 条，其余按时间删除（定时同步必须配合裁剪）。

    **不得**删掉 queued / running 的行 —— 否则用户正在看的进度会突然消失。
    """
    ...


async def recover_stale_runs(session: AsyncSession) -> int:
    """启动清理：把全部残留 queued / running 置为 aborted，返回被标记行数。

    不限于单个 vault —— 进程重启后内存中的 task 全部消失，
    这些行留着会阻塞「是否有作业在跑」的判断，并让用户看到僵尸作业。
    不清理成 cancelled：二者语义不同，cancelled 只用于**用户主动停止**（M03 §5.13.6）。
    """
    ...
