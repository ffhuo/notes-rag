"""业务·文件监听 — 本地 vault 的文件系统事件 → 触发增量同步（**二期预留**）。

状态：watch 默认关闭（settings.watch_enabled=False）；启用时用**轮询快照对比**实现，
不强依赖 watchfiles / inotify（网络挂载通常不产生事件，轮询反而是最稳的跨平台方案）。

硬边界（M03 §5.10.2）：watch **只负责标记「这个 vault 脏了」**，不携带、也不决定
「哪个文件变了、怎么处理」。debounce 窗口结束后走与其他路径**完全相同**的作业提交
（run_service.submit(..., trigger="watch")），互斥 / 幂等 / 进度 / 删除三护栏全部复用，
绝不直连 sync_service 或自己做增删。

主要函数：
- async def start_watcher(vault) -> None
- async def stop_watcher(vault_id: int) -> None
- def is_watchable(vault, local_path) -> bool
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.core.config import settings
from app.models import Vault
from app.services import run_service, sync_service, vault_service

logger = logging.getLogger(__name__)

# 轮询间隔：不短于 debounce，避免高频 stat 空转
_POLL_INTERVAL_S = max(1.0, settings.watch_debounce_ms / 1000.0)

# vault_id → 后台轮询任务
_watchers: dict[int, asyncio.Task] = {}


def is_watchable(vault: Vault, local_path: Path) -> bool:
    """是否可监听：仅 source_type=local、目录真实存在时返回 True。

    一期不对 SMB/NFS 做 fstype 探测（跨平台成本高）；git/remote/uploaded 一律不监听，
    它们的更新由手动 / 定时同步覆盖。
    """
    if (vault.source_type or "").lower() != "local":
        return False
    return local_path.exists() and local_path.is_dir()


async def start_watcher(vault: Vault) -> None:
    """启动对某 vault 的轮询监听；已在监听则先停后启（幂等）。

    settings.watch_enabled=False 时直接 no-op（二期默认关闭）。
    """
    if not settings.watch_enabled:
        logger.info("watch 未启用，跳过 vault=%s 的监听", vault.id)
        return

    try:
        local_path = vault_service.resolve_local_path(vault, settings)
    except vault_service.SourceUnavailable:
        logger.warning("watch 启动失败：源不可达 vault=%s", vault.id)
        return

    if not is_watchable(vault, local_path):
        logger.info("vault=%s 不可监听（非本地源），静默降级", vault.id)
        return

    await stop_watcher(vault.id)
    _watchers[vault.id] = asyncio.create_task(_watch_loop(vault, local_path))
    logger.info("watch 已启动 vault=%s interval=%ss", vault.id, _POLL_INTERVAL_S)


async def stop_watcher(vault_id: int) -> None:
    """停止某 vault 的监听（删除 vault / 关闭 watch / 重启时调用）。"""
    task = _watchers.pop(vault_id, None)
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("watch 已停止 vault=%s", vault_id)


async def _watch_loop(vault: Vault, local_path: Path) -> None:
    """轮询快照 → 标脏 → debounce 静默后提交一次 watch 作业。

    快照只用来回答「有没有变化」，变化内容仍交给 sync 对账（不做第二份判定）。
    """
    debounce_s = settings.watch_debounce_ms / 1000.0
    last_sig = await asyncio.to_thread(_snapshot, local_path)
    dirty_at: float | None = None

    try:
        while True:
            await asyncio.sleep(_POLL_INTERVAL_S)
            current = await asyncio.to_thread(_snapshot, local_path)

            if current != last_sig:
                # 源目录整体消失（快照为空且此前非空）不标脏 —— 删除护栏交给手动/定时 sync
                last_sig = current
                dirty_at = asyncio.get_running_loop().time()
                continue

            if dirty_at is not None:
                now = asyncio.get_running_loop().time()
                if now - dirty_at >= debounce_s:
                    dirty_at = None
                    try:
                        await run_service.submit(vault, mode="sync", trigger="watch")
                    except run_service.AlreadyRunning:
                        # 已有作业在跑：不排队，本次标脏被对账吸收（幂等）
                        logger.info("vault=%s watch 触发时已有作业，跳过", vault.id)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 —— 监听循环不能因一次异常永久死掉
        logger.warning("watch 循环异常 vault=%s", vault.id, exc_info=True)


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """轻量快照：{POSIX 相对路径: (mtime_ns, size)}，复用 sync 的同一套扫描过滤。

    扫描失败（scan_complete=False）时返回空 dict，由下一轮重试 ——
    绝不在不确定状态下触发「删除类」结论。
    """
    seen, complete = sync_service._scan(root, None)
    if not complete:
        return {}
    return {rel: (sig.mtime_ns, sig.size_bytes) for rel, sig in seen.items()}
