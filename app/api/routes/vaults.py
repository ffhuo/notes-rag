"""API·vaults — 前端配置 vault，并把「索引」全部表达为**异步作业**（见 M06 §5.5）。

能力：
- 列出当前用户的 vault
- 新建 vault（JSON）：本地目录（source_value=绝对路径）或 git/remote（source_value=URL）
- 上传 vault（multipart）：上传 .zip，服务端解压后登记为 source_type=uploaded
- 查看 / 删除 vault（删除同时清该 vault 的索引与分块）
- **提交作业**：sync（对账增量）/ reindex（= 全量重建）/ 进度查询 / 取消 / 一致性自检

主要端点：
- GET    /api/v1/vaults                        # 列表
- POST   /api/v1/vaults                        # JSON: { name, source_type: local|git|remote, source_value, filters? }
- POST   /api/v1/vaults/upload                 # multipart: name + file=.zip（source_type=uploaded）
- GET    /api/v1/vaults/browse                 # ?path=<绝对路径>&rel=<相对子路径> 列一层子目录（目录树懒加载）
- GET    /api/v1/vaults/{id}
- PATCH  /api/v1/vaults/{id}                   # 改 name / filters（source_value 不可改）
- DELETE /api/v1/vaults/{id}
- POST   /api/v1/vaults/{id}/sync              # 202 RunSubmitResponse（body: SyncRequest）
- POST   /api/v1/vaults/{id}/reindex           # 202 = sync(mode="rebuild") 的别名；?embed_profile=
- GET    /api/v1/vaults/{id}/runs              # 历史作业列表（?limit=）
- GET    /api/v1/vaults/{id}/runs/{rid}        # 作业详情与进度轮询
- POST   /api/v1/vaults/{id}/runs/{rid}/cancel # 204；已终态 → 409
- GET    /api/v1/vaults/{id}/doctor            # 三向一致性自检
- POST   /api/v1/vaults/{id}/doctor            # ?repair=true 时修复幽灵 / 缺失向量

契约要点（写实现时必须遵守）：
1. **写入类端点一律立即返回 202**，绝不阻塞等作业跑完 —— 全量重建 2–10 min，
   同步返回必撞网关超时。客户端拿 run_id 后轮询 `runs/{rid}`（M03 §5.13.1 / ADR-12）。
2. **同一 vault 已有作业在跑 → 409 + existing_run_id（不排队）**：
   前端据此跳到那个任务的进度视图，而不是拿到一个静默失效的请求（M06 ADR-8）。
3. **取消用 POST 而非 DELETE**：取消只是请求停止执行，记录必须保留
   （它是排查依据与历史），`DELETE /runs/{rid}` 会被读成「删除记录」。
4. 建库 / 上传**不自动索引**：前端建完 vault 后再显式调 `/sync` 提交首个作业。

分层约定：本文件只做「入参校验 + 归属校验 + 调 service + 异常翻译成状态码」，
业务规则（对账、护栏、作业生命周期）全部在 services；DB 读写经 repositories。

关联方案：M06 §5.3（提交语义）/ §5.4（repo 原语）/ §5.5（API 契约）+ ADR-8 / ADR-9；
         M03 §5.7（统一作业语义）/ §5.13（作业化执行与进度）；M07 §5.4（前端进度视图）。
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_settings
from app.core.config import Settings
from app.core.database import get_session
from app.models import SyncRun, Vault
from app.models.schemas import (
    DoctorReport,
    IngestFilters,
    RunSubmitResponse,
    SyncPlan,
    SyncRequest,
    SyncResult,
    SyncRunDetail,
    SyncRunOut,
    VaultBrowseEntry,
    VaultBrowseOut,
    VaultCreate,
    VaultOut,
    VaultUpdate,
)
from app.rag.vectorstore import VectorStore
from app.repositories import sync_repo, vault_repo
from app.services import run_service, sync_service, vault_service
from app.services.ingest_service import ENV_PROFILE_PLACEHOLDER
from app.services.model_service import (
    EmbedModelMismatch,
    ModelNotConfigured,
    ModelNotFound,
    collection_name,
)
from app.services.run_service import AlreadyRunning
from app.services.vault_service import SourceUnavailable

router = APIRouter(prefix="/api/v1/vaults", tags=["vaults"])

# 终态：queued / running 之外的七态中可收尾的五种（M03 §5.13.6）
_TERMINAL_STATUSES = {"success", "partial", "failed", "cancelled", "aborted"}
# SyncPlan.blocked_reason 的合法取值域（DB 列是自由字符串，需收口后再出参）
_BLOCKED_REASONS = {"source_unavailable", "scan_incomplete", "over_ratio", "prune_disabled"}


# ===== 出参构造 =====


def _indexed_profiles(vault: Vault) -> list[int]:
    """vault.embed_indexed_profiles（JSON 字符串）→ int 列表；非法值按空处理。"""
    try:
        raw = json.loads(vault.embed_indexed_profiles or "[]")
    except (ValueError, TypeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, int)]


def _vault_filters(vault: Vault) -> IngestFilters | None:
    """vault.filters_json → IngestFilters；空 / 非法 → None（= 未设置过滤）。

    None 而不是「全 None 的 IngestFilters」：前端据此区分「没配过」与「配了但留空」，
    后者会显式覆盖 settings 默认。
    """
    try:
        raw = json.loads(vault.filters_json or "{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        return IngestFilters.model_validate(raw)
    except ValueError:                      # pydantic ValidationError 继承自 ValueError
        logger.warning("vault.filters_json 非法，按未设置处理", vault_id=vault.id)
        return None


def _epoch_ms(dt: datetime | None) -> int | None:
    """datetime → UTC 毫秒时间戳（出参里所有时间字段的统一格式）。

    库里的时间是**朴素 UTC**：created_at / indexed_at 走 func.now()（SQLite 的
    CURRENT_TIMESTAMP 本身就是 UTC），SyncRun.finished_at 虽由 datetime.now(timezone.utc)
    写入，但 SQLite 不保存偏移，读回来同样是无 tz 的朴素值。所以必须显式补 UTC 再取
    epoch —— 直接 dt.timestamp() 会按**本地时区**解释，东八区下整体偏 8 小时。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _vault_out(vault: Vault) -> VaultOut:
    """Vault → VaultOut（datetime → 毫秒时间戳，JSON 列 → 列表）。"""
    return VaultOut(
        id=vault.id,
        user_id=vault.user_id,
        name=vault.name,
        source_type=vault.source_type,
        source_value=vault.source_value,
        origin=vault.origin,
        indexed_at=_epoch_ms(vault.indexed_at),
        filters=_vault_filters(vault),
        embed_profile_id=vault.embed_profile_id,
        embed_indexed_profiles=_indexed_profiles(vault),
    )


def _run_out(run: SyncRun) -> SyncRunOut:
    """SyncRun → SyncRunOut。

    cancelling 只在「已受理取消且仍未终态」时为 True —— 终态下前端不该再显示
    「正在停止…」（M07 §5.4.5）。
    """
    cancelling = bool(run.cancel_requested) and run.status not in _TERMINAL_STATUSES
    return SyncRunOut(
        id=run.id,
        vault_id=run.vault_id,
        trigger=run.trigger,
        mode=run.mode,
        dry_run=run.dry_run,
        status=run.status,
        stage=run.stage,
        total=run.total,
        processed=run.processed or 0,
        current_item=run.current_item,
        cancelling=cancelling,
        adds=run.adds or 0,
        updates=run.updates or 0,
        moves=run.moves or 0,
        deletes=run.deletes or 0,
        unchanged=run.unchanged or 0,
        failed_cnt=run.failed_cnt or 0,
        blocked_reason=run.blocked_reason,
        error=run.error,
        started_at=_epoch_ms(run.started_at),
        finished_at=_epoch_ms(run.finished_at),
        elapsed_ms=run.elapsed_ms or 0,
    )


def _load_detail(raw: str | None) -> dict:
    """解析 detail_json（失败文件清单 / samples / skipped_reason 等）。"""
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _plan_from_run(run: SyncRun, detail: dict) -> SyncPlan:
    """用作业行的计数列 + detail_json 还原 SyncPlan（dry_run 产物）。"""
    blocked = run.blocked_reason if run.blocked_reason in _BLOCKED_REASONS else None
    return SyncPlan(
        vault_id=run.vault_id,
        mode=run.mode if run.mode in ("sync", "rebuild") else "sync",
        adds=run.adds or 0,
        updates=run.updates or 0,
        moves=run.moves or 0,
        deletes=run.deletes or 0,
        unchanged=run.unchanged or 0,
        prune_blocked=blocked in ("over_ratio", "prune_disabled"),
        blocked_reason=blocked,
        samples=detail.get("samples") or {},
    )


def _result_from_run(run: SyncRun, detail: dict) -> SyncResult:
    """在 SyncPlan 之上补执行信息（failed / failed_files / skipped_reason / elapsed）。"""
    plan = _plan_from_run(run, detail)
    failed_files = detail.get("failed_files") or []
    return SyncResult(
        **plan.model_dump(),
        failed=run.failed_cnt or 0,
        failed_files=failed_files if isinstance(failed_files, list) else [],
        skipped_reason=detail.get("skipped_reason"),
        elapsed_ms=run.elapsed_ms or 0,
    )


def _run_detail(run: SyncRun) -> SyncRunDetail:
    """作业详情：列表字段 + message + 产物（dry_run→plan，执行类→result）。"""
    payload = _run_out(run).model_dump()
    payload["message"] = run.message

    detail = _load_detail(run.detail_json)
    if run.status in _TERMINAL_STATUSES:
        if run.dry_run:
            payload["plan"] = _plan_from_run(run, detail)
        else:
            payload["result"] = _result_from_run(run, detail)
    return SyncRunDetail(**payload)


# ===== 归属校验 =====


async def _get_vault_or_404(session: AsyncSession, vault_id: int, user_id: str) -> Vault:
    """取当前用户的 vault；不存在或不属于该用户一律 404（不泄露存在性）。"""
    vault = await vault_repo.get_vault(session, vault_id, user_id)
    if vault is None:
        raise HTTPException(
            status_code=404, detail=f"vault_id={vault_id} 不存在或不属于当前用户"
        )
    return vault


async def _get_run_or_404(
    session: AsyncSession, vault_id: int, run_id: int, user_id: str
) -> SyncRun:
    """取作业并确认它属于 URL 中那个 vault（避免跨 vault 读取作业详情）。"""
    run = await sync_repo.get_sync_run(session, run_id, user_id)
    if run is None or run.vault_id != vault_id:
        raise HTTPException(status_code=404, detail=f"作业不存在：run_id={run_id}")
    return run


# ===== vault 配置 =====


@router.get("", response_model=list[VaultOut])
async def list_vaults(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """列出当前用户的 vault。"""
    vaults = await vault_repo.list_vaults(session, user_id)
    return [_vault_out(v) for v in vaults]


@router.post("", response_model=VaultOut, status_code=status.HTTP_201_CREATED)
async def create_vault(
    payload: VaultCreate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """新建 vault（不自动索引；建完后前端调 /sync 提交首个作业）。

    source_type: local -> source_value 为绝对路径；git/remote -> source_value 为 URL。
    """
    source_type = (payload.source_type or "").lower()

    if source_type == "local":
        if not payload.source_value:
            raise HTTPException(status_code=422, detail="source_type=local 需提供 source_value（绝对路径）")
        # 早失败：路径打错在「建库」时就报，而不是等 sync 时才发现源不可达
        if not Path(payload.source_value).expanduser().is_dir():
            raise HTTPException(
                status_code=422, detail=f"本地目录不存在或不是目录：{payload.source_value}"
            )
    elif source_type in ("git", "remote"):
        if not payload.source_value:
            raise HTTPException(
                status_code=422, detail=f"source_type={source_type} 需提供 source_value（URL）"
            )
    elif source_type == "uploaded":
        raise HTTPException(
            status_code=422, detail="上传类型请改用 POST /api/v1/vaults/upload（multipart）"
        )
    else:
        raise HTTPException(
            status_code=422, detail=f"未知 source_type={payload.source_type!r}（可选 local / git / remote）"
        )

    filters_json = (
        json.dumps(payload.filters.model_dump(exclude_none=True), ensure_ascii=False)
        if payload.filters is not None
        else "{}"
    )

    vault = await vault_repo.create_vault(
        session,
        user_id=user_id,
        name=payload.name,
        source_type=source_type,
        source_value=payload.source_value or "",
        filters_json=filters_json,
    )
    logger.info("vault 已创建", vault_id=vault.id, source_type=source_type, user_id=user_id)
    return _vault_out(vault)


@router.post("/upload", response_model=VaultOut, status_code=status.HTTP_201_CREATED)
async def upload_vault(
    name: str = Form(...),
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """上传 .zip 建 vault（解压到 UPLOAD_DIR/<vault_id>，不自动索引）。

    先建库拿到 id（源目录名就是 id），再把包解压到该目录并回填 source_value；
    解压失败则回滚刚建的 vault，不留半残记录。
    """
    vault = await vault_repo.create_vault(
        session,
        user_id=user_id,
        name=name,
        source_type="uploaded",
        source_value="",
    )

    try:
        target = await vault_service.save_upload(vault.id, file, settings)
    except ValueError as e:
        # 非法压缩包 / 穿越 / 炸弹：清掉刚建的 vault，避免留下不可用的记录
        await vault_repo.delete_vault(session, vault.id, user_id)
        logger.warning("上传解压失败，已回滚 vault", vault_id=vault.id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    # 回填 source_value 为解压目录（resolve_local_path 依赖它）
    vault.source_value = str(target)
    await session.commit()
    await session.refresh(vault)

    logger.info("uploaded vault 已创建", vault_id=vault.id, path=str(target), user_id=user_id)
    return _vault_out(vault)


@router.get("/browse", response_model=VaultBrowseOut)
async def browse_dirs(
    path: str = Query(..., description="要浏览的根目录绝对路径（通常是 vault 的本地目录）"),
    rel: str = Query("", description="相对根目录的子路径；留空 = 根目录本身"),
    _user_id: str = Depends(get_current_user_id),   # 仅用于强制鉴权，不参与业务
):
    """列出某一层子目录（目录树懒加载），供前端勾选「排除目录」。

    只返回目录、不返回文件：过滤语义是「排除整个文件夹下的内容」，前端把勾选结果
    转成 `<rel>/**` 相对路径 glob 写进 vault.filters.exclude（同步时按目录剪枝）。

    注意：本端点按绝对路径浏览服务器文件系统，多用户部署下任意登录用户都可探测
    目录名（只列目录、不读内容）。如需收紧，应在网关/鉴权层限制而非在此处硬编码。
    """
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=422, detail=f"目录不存在或不是目录：{path}")

    sub = _normalize_rel(rel)
    target = root if not sub else (root / sub).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=422, detail=f"非法子路径：{rel}")
    if not target.is_dir():
        raise HTTPException(status_code=422, detail=f"子目录不存在：{rel}")

    # scandir 是阻塞 IO，放线程池避免卡住事件循环（同 _scan 的处理）
    entries = await asyncio.to_thread(_list_subdirs, target, root)
    return VaultBrowseOut(root=str(root), rel=sub, entries=entries)


def _normalize_rel(raw: str) -> str:
    """归一化前端传来的相对路径；绝对路径 / 含 .. → 422（路径穿越防护）。"""
    text = (raw or "").strip().replace("\\", "/").strip("/")
    if not text:
        return ""
    parts: list[str] = []
    for seg in text.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            raise HTTPException(status_code=422, detail=f"非法子路径：{raw}")
        parts.append(seg)
    return "/".join(parts)


def _list_subdirs(target: Path, root: Path) -> list[VaultBrowseEntry]:
    """列出 target 下的一层子目录（跳过隐藏目录：扫描时本就剪枝，列出只会误导）。"""
    entries: list[VaultBrowseEntry] = []
    try:
        with os.scandir(target) as it:
            for item in it:
                if not item.is_dir(follow_symlinks=False) or item.name.startswith("."):
                    continue
                entries.append(
                    VaultBrowseEntry(
                        name=item.name,
                        rel=Path(item.path).resolve().relative_to(root).as_posix(),
                        has_children=_has_subdir(item.path),
                    )
                )
    except OSError as e:
        raise HTTPException(status_code=422, detail=f"无法读取目录：{target}（{e}）")
    entries.sort(key=lambda x: x.name)
    return entries


def _has_subdir(dir_path: str) -> bool:
    """是否存在下一层可展示的子目录（存在即提前返回，不扫全量）。"""
    try:
        with os.scandir(dir_path) as it:
            for item in it:
                if item.is_dir(follow_symlinks=False) and not item.name.startswith("."):
                    return True
    except OSError:
        return False
    return False


@router.get("/{vault_id}", response_model=VaultOut)
async def get_vault(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """vault 详情（含 *last_sync_* / embed_indexed_profiles 等状态；状态只在作业成功后回写）。"""
    vault = await _get_vault_or_404(session, vault_id, user_id)
    return _vault_out(vault)


@router.patch("/{vault_id}", response_model=VaultOut)
async def update_vault(
    vault_id: int,
    payload: VaultUpdate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """改 vault 的 name / filters（只允许这两个字段，见 schemas.VaultUpdate）。

    **不自动重建索引**：过滤改动在下次 /sync 时生效。改过滤会让「新排除的文件」变成
    待删除（known 里有、seen 里没有），届时仍受删除比例护栏保护。
    传 filters=null 表示清空过滤，回到 settings 默认。
    """
    await _get_vault_or_404(session, vault_id, user_id)

    provided = payload.model_fields_set
    name: str | None = None
    if "name" in provided:
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="name 不能为空")

    filters_json: str | None = None
    if "filters" in provided:
        filters_json = (
            json.dumps(payload.filters.model_dump(exclude_none=True), ensure_ascii=False)
            if payload.filters is not None
            else "{}"
        )

    if name is None and filters_json is None:
        raise HTTPException(status_code=422, detail="未提供任何可更新字段（name / filters）")

    vault = await vault_repo.update_vault(
        session, vault_id, user_id, name=name, filters_json=filters_json
    )
    if vault is None:                       # 归属校验后仍可能被并发删除
        raise HTTPException(status_code=404, detail=f"vault_id={vault_id} 不存在或不属于当前用户")
    logger.info("vault 已更新", vault_id=vault_id, renamed=name is not None, filters_set=filters_json is not None)
    return _vault_out(vault)


@router.delete("/{vault_id}")
async def delete_vault(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """删除 vault：先清向量集合，再级联删 notes / chunks / vault 行。

    有作业在跑 → 409：删除记录与后台协程会互相打脸（协程仍会写进度 / 回写模型状态）。
    用户应先 POST cancel 并等它到终态。
    """
    vault = await _get_vault_or_404(session, vault_id, user_id)

    active = await sync_repo.find_active_run(session, vault.id)
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "existing_run_id": active.id,
                "status": active.status,
                "message": "该 vault 有作业进行中，请先取消并等待其结束后再删除",
            },
        )

    # 清向量：已知建过索引的 profile；从未用 DB profile 建过（历史 env 占位存量数据）则清 env 集合
    targets = _indexed_profiles(vault)
    if not targets and vault.indexed_at is not None:
        targets = [ENV_PROFILE_PLACEHOLDER]
    for profile_id in targets:
        try:
            store = VectorStore(
                persist_dir=settings.chroma_dir,
                collection_name=collection_name(vault.id, profile_id),
            )
            await store.reset()
        except Exception:  # noqa: BLE001 —— 向量清理失败不应阻塞 DB 删除；doctor 可再查
            logger.warning(
                "清理 vault 向量集合失败 vault=%s profile=%s", vault.id, profile_id, exc_info=True
            )

    await vault_repo.delete_vault(session, vault.id, user_id)
    logger.info("vault 已删除", vault_id=vault.id, user_id=user_id)
    return {"deleted": True, "id": vault_id}


# ===== 作业：提交 / 进度 / 取消 =====


async def _submit(
    vault: Vault,
    settings: Settings,
    *,
    embed_profile_ref: str | None,
    mode: str,
    dry_run: bool,
    prune: bool,
    force: bool,
    filters,
) -> SyncRun:
    """提交作业并把领域异常翻译成 HTTP 状态码（sync / reindex 共用）。"""
    try:
        return await vault_service.submit_sync(
            vault=vault,
            settings=settings,
            embed_profile_ref=embed_profile_ref,
            mode=mode,
            dry_run=dry_run,
            prune=prune,
            force=force,
            filters=filters,
            trigger="manual",
        )
    except AlreadyRunning as e:
        # 同 vault 不排队：前端据 existing_run_id 直接跳到那个任务的进度视图（ADR-8）
        raise HTTPException(
            status_code=409,
            detail={
                "existing_run_id": e.existing_run_id,
                "status": e.status,
                "message": "该 vault 已有作业进行中（不排队）",
            },
        )
    except ModelNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ModelNotConfigured:
        raise HTTPException(
            status_code=409,
            detail="尚未配置向量模型：请到「模型」页新增一个 kind=embed 的配置",
        )
    except EmbedModelMismatch as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/{vault_id}/sync",
    response_model=RunSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_vault(
    vault_id: int,
    payload: SyncRequest = SyncRequest(),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """提交一次同步作业（默认 mode="sync" 增量对账）→ 202。

    202 只表示**已受理**，不代表完成。dry_run=true 时作业只对账不写入，
    产物 SyncPlan 挂在详情接口的 plan 字段上。
    """
    vault = await _get_vault_or_404(session, vault_id, user_id)
    run = await _submit(
        vault,
        settings,
        embed_profile_ref=payload.embed_profile,
        mode=payload.mode,
        dry_run=payload.dry_run,
        prune=payload.prune,
        force=payload.force,
        filters=payload.filters,
    )
    return RunSubmitResponse(run_id=run.id, vault_id=run.vault_id, status=run.status)


@router.post(
    "/{vault_id}/reindex",
    response_model=RunSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_vault(
    vault_id: int,
    embed_profile: str | None = Query(
        default=None, description="换 embedding 重建（name 或 id，见 M08）；留空 = 当前默认"
    ),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """全量重建索引 → 202（= sync 的 mode="rebuild" 特例，不是另一套代码路径）。

    何时需要：换 embedding / 改分块参数 / 索引疑似损坏（先跑 doctor 确认）。
    重建会先 reset 该 collection 再全量写入，中途失败会得到 partial 而非静默半残。
    """
    vault = await _get_vault_or_404(session, vault_id, user_id)
    run = await _submit(
        vault,
        settings,
        embed_profile_ref=embed_profile,
        mode="rebuild",
        dry_run=False,
        prune=True,
        force=False,
        filters=None,
    )
    return RunSubmitResponse(run_id=run.id, vault_id=run.vault_id, status=run.status)


@router.get("/{vault_id}/runs", response_model=list[SyncRunOut])
async def list_runs(
    vault_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """历史作业列表（前端「任务与进度」用）。

    **返回全部状态**，由前端把运行中的置顶 —— 不要在 SQL 层过滤掉已完成的行，
    否则用户刚跑完的任务会突然消失。
    """
    await _get_vault_or_404(session, vault_id, user_id)
    runs = await sync_repo.list_sync_runs(session, vault_id, limit)
    return [_run_out(r) for r in runs]


@router.get("/{vault_id}/runs/{run_id}", response_model=SyncRunDetail)
async def get_run(
    vault_id: int,
    run_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """作业详情与**进度轮询**（前端 1s 轮询，M07 §5.4.5）。

    出参关键：
    - stage / total / processed / current_item：进度条依据；
      **total 为 None ⇒ 该阶段总量不可知**（scan）→ 前端转「不确定态」滚动条，不硬编分母
    - cancelling=true ⇒ 已受理取消但循环尚未到文件边界 → 前端显示「正在停止…」并禁用按钮
    - 终态七态里 failed / cancelled / aborted 语义不同，前端文案不可混用（M03 §5.13.6）
    """
    await _get_vault_or_404(session, vault_id, user_id)
    run = await _get_run_or_404(session, vault_id, run_id, user_id)
    return _run_detail(run)


@router.post("/{vault_id}/runs/{run_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_run(
    vault_id: int,
    run_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """请求取消作业 → 204（**协作式**，在文件边界生效，M03 ADR-14）。

    - 已终态 → 409（没什么可取消的）；重复取消幂等
    - 返回 204 ≠ 已停止：任务可能还要跑完当前文件。前端应显示「正在停止…」并继续轮询，
      直到 status 变为 cancelled（部分完成的结果会保留）
    """
    await _get_vault_or_404(session, vault_id, user_id)
    await _get_run_or_404(session, vault_id, run_id, user_id)

    accepted = await run_service.request_cancel(run_id)
    if not accepted:
        raise HTTPException(
            status_code=409, detail=f"作业已结束，无法取消：run_id={run_id}"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===== 一致性自检 =====


async def _doctor(
    vault: Vault, settings: Settings, *, repair: bool
) -> DoctorReport:
    """解析本地路径后跑三向一致性自检（源不可达 → 409，无法自检）。"""
    try:
        local_path = vault_service.resolve_local_path(vault, settings)
    except SourceUnavailable as e:
        raise HTTPException(status_code=409, detail=str(e))
    return await sync_service.doctor(vault, local_path, repair=repair)


@router.get("/{vault_id}/doctor", response_model=DoctorReport)
async def doctor(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """三向一致性自检：Chroma ↔ chunks ↔ 磁盘（只读，不改任何东西）。"""
    vault = await _get_vault_or_404(session, vault_id, user_id)
    return await _doctor(vault, settings, repair=False)


@router.post("/{vault_id}/doctor", response_model=DoctorReport)
async def doctor_repair(
    vault_id: int,
    repair: bool = Query(default=False, description="true 时修复幽灵向量与缺失向量"),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    """一致性自检（可修复）。

    repair=true 只修**幽灵向量 / 缺失向量**；孤儿笔记交给 sync、模型错配交给 reindex
    —— 修复策略刻意保守，不做复杂补偿事务（M03 §5.12）。
    """
    vault = await _get_vault_or_404(session, vault_id, user_id)
    return await _doctor(vault, settings, repair=repair)