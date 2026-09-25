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

关联方案：M06 §5.3（提交语义）/ §5.4（repo 原语）/ §5.5（API 契约）+ ADR-8 / ADR-9；
         M03 §5.7（统一作业语义）/ §5.13（作业化执行与进度）；M07 §5.4（前端进度视图）。
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.core.database import get_session
from app.models.schemas import (
    DoctorReport,
    RunSubmitResponse,
    SyncRequest,
    SyncRunDetail,
    SyncRunOut,
    VaultCreate,
    VaultOut,
)
from app.services import run_service, vault_service

router = APIRouter(prefix="/api/v1/vaults", tags=["vaults"])


@router.get("", response_model=list[VaultOut])
async def list_vaults(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """列出当前用户的 vault。"""
    ...


@router.post("", response_model=VaultOut, status_code=status.HTTP_201_CREATED)
async def create_vault(
    payload: VaultCreate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """新建 vault（不自动索引；建完后前端调 /sync 提交首个作业）。

    source_type: local -> source_value 为绝对路径；git/remote -> source_value 为 URL。
    """
    ...


@router.post("/upload", response_model=VaultOut, status_code=status.HTTP_201_CREATED)
async def upload_vault(
    name: str = Form(...),
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # 1) 建 vault（source_type="uploaded"）拿 vault_id
    # 2) vault_service.save_upload(vault_id, file) 解压到 UPLOAD_DIR/<vault_id>
    # 3) 回填 source_value 为该目录
    # 注意：FastAPI 同一端点不能同时收 Pydantic body 与 UploadFile，故上传单列一个端点。
    ...


@router.get("/{vault_id}", response_model=VaultOut)
async def get_vault(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """vault 详情（含 *last_sync_* / embed_indexed_profiles 等状态；状态只在作业成功后回写）。"""
    ...


@router.delete("/{vault_id}")
async def delete_vault(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    # 1) 校验归属 → 2) 清该 vault 的 notes/chunks（vault_repo.delete_vault）
    # 3) 清向量库（vectorstore 按 vault_id 删集合）→ 4) 级联删 sync_runs
    # 若该 vault 有作业在跑：先请求取消或直接 409（避免删表与后台协程互相打脸）
    ...


# ===== 作业：提交 / 进度 / 取消 =====


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
):
    """提交一次同步作业（默认 mode="sync" 增量对账）→ 202。

    实现步骤：
    1) 校验 vault 归属 → resolve_local_path 求本地目录
    2) 解析 embedding：payload.embed_profile（name 或 id）→ 用户默认 → .env 兜底（M08 §4）
       **换 embedding 必须 mode="rebuild"** —— 增量会让同一 collection 混入两种向量空间的向量
    3) run_service.submit(vault, mode=..., dry_run=..., prune=..., force=...,
                          filters=..., embed_runtime=..., trigger="manual")
    4) 抢不到锁 → run_service.AlreadyRunning → 409 + {existing_run_id, status}（M06 ADR-8）

    status="queued"（刚落库）或 "running"（已抢到锁）。**不代表已完成**。
    dry_run=true 时作业会停在 stage=plan_ready，产物 SyncPlan 挂在详情接口的 plan 字段上。
    """
    ...


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
):
    """全量重建索引 → 202（= sync 的 mode="rebuild" 特例，不是另一套代码路径）。

    何时需要：换 embedding / 改分块参数 / 索引疑似损坏（先跑 doctor 确认）。
    重建会先 reset 该 collection 再全量写入，中途失败会得到 partial 而非静默半残。
    """
    ...


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
    ...


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
    ...


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
    ...


# ===== 一致性自检 =====


@router.get("/{vault_id}/doctor", response_model=DoctorReport)
async def doctor(
    vault_id: int,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """三向一致性自检：Chroma ↔ chunks ↔ 磁盘（只读，不改任何东西）。"""
    ...


@router.post("/{vault_id}/doctor", response_model=DoctorReport)
async def doctor_repair(
    vault_id: int,
    repair: bool = Query(default=False, description="true 时修复幽灵向量与缺失向量"),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
):
    """一致性自检（可修复）。

    repair=true 只修**幽灵向量 / 缺失向量**；孤儿笔记交给 sync、模型错配交给 reindex
    —— 修复策略刻意保守，不做复杂补偿事务（M03 §5.12）。
    """
    ...
