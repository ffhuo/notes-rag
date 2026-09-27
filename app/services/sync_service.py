"""业务·变更管理 — vault 文件变化（新增 / 修改 / 删除 / 改名）的对账与同步。

能力：
- 两段式变更判据：L1 = size_bytes + mtime_ns（stat 即得，零额外 IO）；
  L2 = content_hash（仅 L1 不一致或新增时计算，识别「时间戳变了但内容没变」）
- 四类变更对账：新增 / 修改 / 移动（内容不变仅改名，零 embedding）/ 删除
- 删除三护栏（M03 ADR-7）：源可达 / 扫描完整 / 删除比例（默认 0.5，force 可越过）
- dry_run：只算不写，返回计数计划
- doctor：Chroma ↔ chunks ↔ notes 一致性自检

边界：本模块只决定「做什么」；「怎么做」全部委托 ingest_service 的文件级原语
（index_file / drop_file / move_file），与 API 上传等路径共用同一实现。

与 run_service 分工：本模块保持**同步语义**（sync_vault 跑到结束才返回），
「何时跑、进度怎么写、能否取消」由 run_service 通过 ProgressSink 协议注入，
本模块**不 import run_service**。

关联方案：M03 §5.8–§5.12；docs/design.md §4.1 / §5.1.1。
"""
from __future__ import annotations

import asyncio
import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from loguru import logger

from app.core.config import settings
from app.core.database import session_scope
from app.models import Vault
from app.models.schemas import DoctorReport, IngestFilters, ModelRuntime, SyncResult
from app.rag.vectorstore import VectorStore
from app.repositories import note_repo
from app.services import ingest_service
from app.services.model_service import collection_name


class ProgressSink(Protocol):
    """run_service 注入的进度协议（本模块只依赖协议，不依赖作业层实现）。"""

    async def advance(self, stage: str, total: Optional[int] = None) -> None: ...

    async def tick(self, item: Optional[str] = None, message: Optional[str] = None) -> None: ...

    def cancel_requested(self) -> bool: ...


@dataclass
class FileSig:
    """单文件变更判据：L1（size/mtime）+ L2（content_hash，按需计算）。"""

    rel_path: str
    size_bytes: int
    mtime_ns: int
    content_hash: str = ""


@dataclass
class ReconcilePlan:
    """对账结果：四类变更 + 未变 + 路径样本（用于 dry_run 展示）。"""

    adds: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    moves: list[tuple[str, str]] = field(default_factory=list)  # (old_path, new_path)
    unchanged: list[str] = field(default_factory=list)

    @property
    def total_changes(self) -> int:
        return len(self.adds) + len(self.updates) + len(self.deletes) + len(self.moves)

    def samples(self, limit: int = 10) -> dict[str, list[str]]:
        return {
            "adds": self.adds[:limit],
            "updates": self.updates[:limit],
            "moves": [f"{o} -> {n}" for o, n in self.moves[:limit]],
            "deletes": self.deletes[:limit],
        }


# ===== 入口编排 =====


async def sync_vault(
    vault: Vault,
    local_path: Path,
    mode: str = "sync",
    dry_run: bool = False,
    prune: bool = True,
    force: bool = False,
    filters: "Optional[IngestFilters]" = None,
    embed_runtime: "ModelRuntime | None" = None,
    embed_profile_id: "int | str | None" = None,
    trigger: str = "manual",
    progress: "ProgressSink | None" = None,
) -> SyncResult:
    """对账并同步一个 vault 的索引，跑到结束返回 SyncResult。"""
    start = time.monotonic()
    result = SyncResult(vault_id=vault.id, mode=mode)  # type: ignore[call-arg]

    # [probe] 源可达校验（护栏 1）。不可达 → ABORT，绝不当成「内容全删了」
    if progress:
        await progress.advance("probe", None)
    if not local_path.exists() or not local_path.is_dir():
        result.blocked_reason = "source_unavailable"
        result.prune_blocked = True
        result.skipped_reason = f"源不可达：{local_path}"
        logger.error("sync 中止：源不可达", vault_id=vault.id, path=str(local_path))
        return result

    # [scan] 遍历磁盘：此阶段只统计文件数，总量事先不可知 → None（前端显示不确定态）
    if progress:
        await progress.advance("scan", None)
    # os.walk + stat 是同步阻塞 IO，放到线程池，避免卡住事件循环
    seen, scan_complete = await asyncio.to_thread(_scan, local_path, filters)

    async with session_scope() as session:
        known = await note_repo.list_note_paths(session, vault.id)

    # rebuild：跳过对账，清空后全部当新增
    if mode == "rebuild":
        return await _run_rebuild(
            vault, local_path, seen, embed_runtime, embed_profile_id,
            dry_run, start, result, progress,
        )

    # [diff] 需要算 hash（L2）的文件 = 新增 + L1 不一致，这批文件数就是本阶段的确定总量，
    # 也是用户能看到的第一个「本次要处理多少文件」的数（M03 §5.13.3）
    need_hash: list[str] = []
    for rel, sig in seen.items():
        n = known.get(rel)
        if n is None or n.size_bytes != sig.size_bytes or n.mtime_ns != sig.mtime_ns:
            need_hash.append(rel)
    if progress:
        await progress.advance("diff", len(need_hash))

    sigs: dict[str, FileSig] = {}
    need_hash_set = set(need_hash)
    for rel, sig in seen.items():
        if rel in need_hash_set:
            sig.content_hash = await asyncio.to_thread(
                ingest_service.file_content_hash, local_path / rel
            )
            if progress:
                await progress.tick(rel, f"比对 {rel}")
            # 紧密循环里让出事件循环，避免长时间独占（M03 §5.13.8）
            await _yield()
        sigs[rel] = sig

    # 对账 + 护栏 2/3
    plan, blocked_reason = reconcile(
        sigs, known, settings.prune_ratio_limit,
        force=force, prune_enabled=prune, scan_complete=scan_complete,
    )
    result.adds = len(plan.adds)
    result.updates = len(plan.updates)
    result.moves = len(plan.moves)
    result.deletes = len(plan.deletes)
    result.unchanged = len(plan.unchanged)
    result.blocked_reason = blocked_reason
    result.prune_blocked = blocked_reason is not None
    result.samples = plan.samples()

    if dry_run:
        result.skipped_reason = "dry_run"
        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result

    # [index] 执行（移动 → 新增/修改 → 删除）
    total = len(plan.adds) + len(plan.updates) + len(plan.moves) + len(plan.deletes)
    if progress:
        await progress.advance("index", total)

    cancelled = await _apply_plan(
        vault, local_path, known, plan, embed_runtime, embed_profile_id,
        allow_delete=blocked_reason is None, result=result, progress=progress,
    )

    result.elapsed_ms = int((time.monotonic() - start) * 1000)
    if cancelled:
        result.skipped_reason = "cancelled"
    return result


# ===== 判据与对账（纯逻辑，可单测）=====


def compute_file_sig(path: Path, rel_path: str, with_hash: bool = False) -> FileSig:
    """计算单文件判据。with_hash=False 只取 L1（stat），True 再算 L2（sha256 前 16 位）。"""
    st = path.stat()
    return FileSig(
        rel_path=rel_path,
        size_bytes=st.st_size,
        mtime_ns=st.st_mtime_ns,
        content_hash=ingest_service.file_content_hash(path) if with_hash else "",
    )


def reconcile(
    signatures: dict[str, FileSig],
    known_notes: dict,
    ratio_limit: float,
    *,
    force: bool = False,
    prune_enabled: bool = True,
    scan_complete: bool = True,
) -> tuple[ReconcilePlan, Optional[str]]:
    """把 seen 与 known 的差集分类为四类变更，做移动配对与删除护栏判定。

    返回 (plan, blocked_reason)：blocked_reason=None 允许删除；
    否则为 scan_incomplete / prune_disabled / over_ratio（此时调用方只增不删）。
    """
    plan = ReconcilePlan()
    seen_keys = set(signatures)
    known_keys = set(known_notes)

    add_candidates = seen_keys - known_keys
    delete_candidates = known_keys - seen_keys

    # 共有文件：L1 相同 → 未变；L1 不同再看 L2
    for rel in seen_keys & known_keys:
        s, n = signatures[rel], known_notes[rel]
        if n.size_bytes == s.size_bytes and n.mtime_ns == s.mtime_ns:
            plan.unchanged.append(rel)
        elif s.content_hash and n.content_hash and s.content_hash == n.content_hash:
            plan.unchanged.append(rel)  # 仅触碰时间戳，内容未变
        else:
            plan.updates.append(rel)

    # 移动配对：content_hash 在删除候选与新增候选中各自恰好出现一次才配对（保守）
    add_buckets: dict[str, list[str]] = {}
    del_buckets: dict[str, list[str]] = {}
    for p in add_candidates:
        h = signatures[p].content_hash
        if h:
            add_buckets.setdefault(h, []).append(p)
    for p in delete_candidates:
        h = known_notes[p].content_hash
        if h:
            del_buckets.setdefault(h, []).append(p)

    paired_adds: set[str] = set()
    paired_dels: set[str] = set()
    for h, add_paths in add_buckets.items():
        del_paths = del_buckets.get(h, [])
        if len(add_paths) == 1 and len(del_paths) == 1:
            old, new = del_paths[0], add_paths[0]
            plan.moves.append((old, new))
            paired_adds.add(new)
            paired_dels.add(old)

    plan.adds = sorted(add_candidates - paired_adds)
    plan.deletes = sorted(delete_candidates - paired_dels)
    plan.updates.sort()
    plan.unchanged.sort()

    # 护栏 2 / 3（源可达已在入口判定）
    blocked: Optional[str] = None
    if not prune_enabled:
        blocked = "prune_disabled"
    elif not scan_complete:
        blocked = "scan_incomplete"
    elif known_keys and not force:
        ratio = len(plan.deletes) / len(known_keys)
        if ratio > ratio_limit:
            blocked = "over_ratio"

    return plan, blocked


# ===== 执行 =====


async def _apply_plan(
    vault, local_path, known, plan: ReconcilePlan,
    embed_runtime, embed_profile_id, allow_delete: bool,
    result: SyncResult, progress,
) -> bool:
    """执行对账计划，返回是否被取消。失败计入 result.failed_files。"""
    cancelled = False

    # 1) 移动（零 embedding）
    for old, new in plan.moves:
        if progress and progress.cancel_requested():
            cancelled = True
            break
        try:
            await ingest_service.move_file(vault, known[old].id, new)
        except Exception as e:  # noqa: BLE001
            result.failed += 1
            result.failed_files.append({"path": new, "reason": f"move: {e}"})
        if progress:
            await progress.tick(new, f"移动 {new}")

    # 2) 新增 / 修改
    for rel in plan.adds + plan.updates:
        if cancelled or (progress and progress.cancel_requested()):
            cancelled = True
            break
        try:
            n = await ingest_service.index_file(
                vault, local_path / rel, rel,
                embed_runtime=embed_runtime,
                embed_profile_id=embed_profile_id,
            )
            if n == 0 and rel in plan.adds:
                # 无解析器/空文件：从新增计数中摘掉，避免误导
                result.adds = max(0, result.adds - 1)
        except Exception as e:  # noqa: BLE001
            result.failed += 1
            result.failed_files.append({"path": rel, "reason": str(e)})
            logger.error("索引文件失败", path=rel, error=str(e))
        if progress:
            await progress.tick(rel, f"索引 {rel}")
        # 紧密循环里让出事件循环，避免长时间独占（M03 §5.13.8）
        await _yield()

    # 3) 删除（护栏未通过则只增不删）
    if allow_delete:
        async with session_scope() as session:
            for rel in plan.deletes:
                if cancelled or (progress and progress.cancel_requested()):
                    cancelled = True
                    break
                note = await note_repo.get_note_by_path(session, vault.id, rel)
                if note is None:
                    continue
                try:
                    await ingest_service.drop_file(vault, note.id)
                except Exception as e:  # noqa: BLE001
                    result.failed += 1
                    result.failed_files.append({"path": rel, "reason": f"delete: {e}"})
                if progress:
                    await progress.tick(rel, f"删除 {rel}")
    # 若被护栏拦截，删除计数保留在计划里但不执行；标注实际未删
    if not allow_delete:
        result.deletes = 0

    return cancelled


async def _run_rebuild(
    vault, local_path, seen, embed_runtime, embed_profile_id,
    dry_run, start, result: SyncResult, progress,
) -> SyncResult:
    """rebuild：重置目标集合 + 清空 DB 行，再全量索引（mode=rebuild 特例，非另一套路径）。"""
    all_paths = sorted(seen.keys())
    result.adds = len(all_paths)
    result.samples = {"adds": all_paths[:10]}

    if dry_run:
        result.skipped_reason = "dry_run"
        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result

    if progress:
        await progress.advance("index", len(all_paths))

    profile_id = embed_profile_id or vault.embed_profile_id or ingest_service.ENV_PROFILE_PLACEHOLDER
    store = VectorStore(
        persist_dir=settings.chroma_dir,
        collection_name=collection_name(vault.id, profile_id),
    )
    async with session_scope() as session:
        await note_repo.clear_vault(session, vault.id)
    await store.reset()

    failed: list[dict] = []
    indexed = 0
    cancelled = False
    for rel in all_paths:
        if progress and progress.cancel_requested():
            cancelled = True
            break
        try:
            n = await ingest_service.index_file(
                vault, local_path / rel, rel,
                embed_runtime=embed_runtime,
                embed_profile_id=profile_id,
            )
            if n > 0:
                indexed += 1
        except Exception as e:  # noqa: BLE001
            failed.append({"path": rel, "reason": str(e)})
            logger.error("rebuild 索引失败", path=rel, error=str(e))
        if progress:
            await progress.tick(rel, f"重建 {rel}")
        await _yield()

    result.adds = indexed
    result.failed = len(failed)
    result.failed_files = failed
    result.elapsed_ms = int((time.monotonic() - start) * 1000)
    if cancelled:
        result.skipped_reason = "cancelled"
    return result


# ===== 扫描与过滤 =====


def _scan(root: Path, filters: "Optional[IngestFilters]") -> tuple[dict[str, FileSig], bool]:
    """遍历目录，返回 {POSIX 相对路径: FileSig(仅 L1)}；scan_complete=False 表示有遍历错误。"""
    exts = _norm_exts(filters.exts if filters and filters.exts else settings.ingest_exts)
    exclude_dirs = set(settings.ingest_exclude_dirs)
    max_size = (
        filters.max_file_size if filters and filters.max_file_size
        else settings.max_file_size
    )
    includes = filters.include if filters and filters.include else None
    excludes = filters.exclude if filters and filters.exclude else None
    # 整目录排除的前缀集合：命中即在 os.walk 层剪掉整棵子树（见 _exclude_dir_prefixes）
    exclude_prefixes = _exclude_dir_prefixes(excludes)

    seen: dict[str, FileSig] = {}
    scan_complete = True

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        keep: list[str] = []
        for d in dirnames:
            if d in exclude_dirs or d.startswith("."):
                continue
            sub_rel = d if rel_dir == "." else f"{rel_dir}/{d}"
            if sub_rel in exclude_prefixes:
                continue
            keep.append(d)
        # 原地修改 dirnames 实现目录剪枝
        dirnames[:] = keep
        for fn in filenames:
            abs_p = Path(dirpath) / fn
            rel = abs_p.relative_to(root).as_posix()
            try:
                if abs_p.suffix.lower() not in exts:
                    continue
                if includes and not any(fnmatch.fnmatch(rel, pat) for pat in includes):
                    continue
                if excludes and any(fnmatch.fnmatch(rel, pat) for pat in excludes):
                    continue
                st = abs_p.stat()
                if st.st_size > max_size:
                    continue
                seen[rel] = FileSig(rel_path=rel, size_bytes=st.st_size, mtime_ns=st.st_mtime_ns)
            except OSError as e:
                scan_complete = False
                logger.warning("扫描文件失败", path=rel, error=str(e))

    return seen, scan_complete


def _exclude_dir_prefixes(excludes: "Optional[list[str]]") -> set[str]:
    """从 filters.exclude 里提取「整目录排除」的目录前缀，供 os.walk 剪枝。

    只认 `<目录>/**` 与 `<目录>/` 两种写法，且目录部分不含通配符 —— 这两类模式在
    文件级 fnmatch 下的效果就是「整棵子树全排除」，故按目录前缀剪枝不会改变结果，
    只是省掉大量 stat 与目录遍历。其余写法（如 `*.tmp`、`**/build/**`）不剪枝，
    由文件级 fnmatch 兜底（fnmatch 的 `*` 会跨 `/` 匹配，嵌套场景依然生效）。
    """
    out: set[str] = set()
    for pat in excludes or []:
        p = pat.strip()
        if p.endswith("/**"):
            prefix = p[:-3]
        elif p.endswith("/"):
            prefix = p.rstrip("/")
        else:
            continue
        if prefix.startswith("./"):
            prefix = prefix[2:]
        if not prefix or any(ch in prefix for ch in "*?["):
            continue
        out.add(prefix)
    return out


def _norm_exts(exts: list[str]) -> set[str]:
    out: set[str] = set()
    for e in exts:
        e = e.strip().lower()
        if not e:
            continue
        out.add(e if e.startswith(".") else f".{e}")
    return out


async def _yield() -> None:
    await asyncio.sleep(0)


# ===== doctor =====


async def doctor(vault: Vault, local_path: Path, repair: bool = False) -> DoctorReport:
    """Chroma ↔ chunks ↔ notes 三向一致性自检（M03 §5.12）。"""
    profile_id = vault.embed_profile_id or ingest_service.ENV_PROFILE_PLACEHOLDER
    store = VectorStore(
        persist_dir=settings.chroma_dir,
        collection_name=collection_name(vault.id, profile_id),
    )

    async with session_scope() as session:
        db_chunks = await note_repo.list_chunks_by_vault(session, vault.id)
        notes = await note_repo.list_note_paths(session, vault.id)

    db_ids = {c.vector_id for c in db_chunks}
    chroma_ids = set(await store.get_all_ids())

    ghost = sorted(chroma_ids - db_ids)       # Chroma 有 / DB 无：最高危
    missing = sorted(db_ids - chroma_ids)     # DB 有 / Chroma 无

    # 孤儿笔记：notes 存在但没有任何 chunk
    noted_ids = {c.note_id for c in db_chunks}
    orphan = [p for p, n in notes.items() if n.id not in noted_ids]

    report = DoctorReport(
        vault_id=vault.id,
        ghost_vectors=len(ghost),
        missing_vectors=len(missing),
        orphan_notes=len(orphan),
        model_mismatch=False,
        samples={
            "ghost_vectors": ghost[:10],
            "missing_vectors": missing[:10],
            "orphan_notes": orphan[:10],
        },
    )

    if repair and ghost:
        # 修复策略刻意保守：只删幽灵向量；缺失向量交给一次 sync/rebuild 重建
        await store.delete(ghost)
        logger.info("doctor 修复：删除幽灵向量", vault_id=vault.id, count=len(ghost))

    return report
