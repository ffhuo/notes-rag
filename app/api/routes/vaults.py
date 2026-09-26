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
- GET    /api/v1/vaults/{id}
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
import json
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
    RunSubmitResponse,
    SyncPlan,
    SyncRequest,
    SyncResult,
    SyncRunDetail,
    SyncRunOut,
    VaultCreate,
    VaultOut,
)
from app.rag.vectorstore import VectorStore
from app.repositories import sync_repo, vault_repo
from app.services import run_service, sync_service, vault_service
from app.services.ingest_service import ENV_PROFILE_PLACEHOLDER
from app.services.model_service import (
    EmbedModelMismatch,
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


def _vault_out(vault: Vault) -> VaultOut:
    """Vault → VaultOut（datetime → ISO 字符串，JSON 列 → 列表）。"""
    return VaultOut(
        id=vault.id,
        user_id=vault.user_id,
        name=vault.name,
        source_type=vault.source_type,
        source_value=vault.source_value,
        origin=vault.origin,
        indexed_at=vault.indexed_at.isoformat() if vault.indexed_at else None,
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
        started_at=run.started_at.isoformat() if run.started_at else None,
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
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


@router.get("/{vault_id}", response_model=VaultOut)
async def get_vault(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """vault 详情（含 *last_sync_* / embed_indexed_profiles 等状态；状态只在作业成功后回写）。"""
    vault = await _get_vault_or_404(session, vault_id, user_id)
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

    # 清向量：已知建过索引的 profile；从未用 DB profile 建过（.env 兜底）则清 env 集合
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