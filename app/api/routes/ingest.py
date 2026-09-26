"""路由·摄取 — POST /api/v1/ingest（CLI / MCP 的入口，见 M03 §5.7）。

能力：
- 接收 vault_path / vault_sources / vault_id / mode / dry_run / prune / force /
  filters / embed_profile
- **只做三件事**：解析入参 → 幂等 upsert 成 vault 实体 → 逐个 `vault_service.submit_sync` 提交作业
- 返回 IngestSubmitResponse（202）：vault_ids / run_ids / skipped

为什么本端点不含编排逻辑：
它是「按源提交作业」的薄适配层，与前端走 `/vaults/{id}/sync` 提交的是**同一个作业模型**。
若在此内联对账 / 索引逻辑，就会出现第二份编排代码，必然与 sync 路径漂移（M03 §5.6）。

多源 = 多作业：`vault_sources` 有几个源就提交几个作业，各自独立推进 / 独立取消 / 独立终态。
某个源被跳过（如该 vault 已有作业在跑）不使整体失败 —— 记入 `skipped` 并附现有 run_id，
调用方据此直接跟进那个任务，而不是重试（同 vault 不排队，M06 ADR-8）。

embedding 选择：req.embed_profile（name 或 id）→ 用户默认 → .env 兜底（M08 §4）；
索引写入 collection_name(vault_id, profile_id)，成功后回写 vault.embed_profile_id /
embed_indexed_profiles（**失败 / 取消时保持原值**，M06 ADR-9）。

主要端点：
- POST /api/v1/ingest → 202 IngestSubmitResponse

关联方案：M03 §5.7（统一作业语义）/ §5.13（作业化执行）；M06 §5.3–§5.5；M08（多模型）。
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_api_key, get_current_user_id, get_session, get_settings
from app.core.config import Settings
from app.models import Vault
from app.models.schemas import IngestRequest, IngestSubmitResponse
from app.services import vault_service
from app.repositories import vault_repo
from app.services.run_service import AlreadyRunning

router = APIRouter(prefix="/api/v1", tags=["ingest"])


def _parse_source(raw: str) -> dict:
    """解析单个源字符串为 {type, source_type, source_value}。

    格式：`<source_type>:<source_value>`，如 `local:/path/to/vault`、`git:https://...`。
    无前缀时默认为 local（兼容裸路径）。
    """
    if ":" in raw:
        prefix, _, value = raw.partition(":")
        # 排除 Windows 盘符（C:\...）被误判为前缀
        if len(prefix) > 1 and prefix in ("local", "uploaded", "git", "remote"):
            return {"type": "source", "source_type": prefix, "source_value": value}
    return {"type": "source", "source_type": "local", "source_value": raw}


def _normalize_sources(req: IngestRequest) -> list[dict]:
    """归一化源列表。

    - vault_id：已存在的 vault 实体
    - vault_path / vault_sources：需 upsert 成 vault 实体（格式 `<type>:<value>`）
    """
    sources: list[dict] = []

    if req.vault_id is not None:
        sources.append({"type": "vault_id", "value": req.vault_id})

    if req.vault_sources:
        for src in req.vault_sources:
            sources.append(_parse_source(src))

    if req.vault_path:
        sources.append(_parse_source(req.vault_path))

    return sources


async def _upsert_vault(
    session: AsyncSession,
    user_id: str,
    source_type: str,
    source_value: str,
) -> Vault:
    """幂等 upsert：同 owner + 同 source_value 不重复建。"""
    existing = await vault_repo.find_by_source(session, user_id, source_value)
    if existing is not None:
        return existing

    # 从路径提取目录名作为 vault 名
    from pathlib import Path
    name = Path(source_value).name or source_value

    return await vault_repo.create_vault(
        session,
        user_id=user_id,
        name=name,
        source_type=source_type,
        source_value=source_value,
    )


@router.post("/ingest", response_model=IngestSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    req: IngestRequest,
    _: str = Depends(get_current_api_key),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> IngestSubmitResponse:
    """提交索引作业（202 = 已受理，不代表已完成）。

    步骤：
    1) 归一化源列表：vault_id（已存在）/ vault_sources / vault_path
    2) 对每个源幂等 upsert 出 vault 实体
    3) 逐个 vault_service.submit_sync(...)；AlreadyRunning → 记入 skipped
    4) 汇总返回 { vault_ids, run_ids, skipped }
    """
    sources = _normalize_sources(req)
    if not sources:
        return IngestSubmitResponse(
            vault_ids=[],
            run_ids=[],
            skipped=[{"reason": "no_source", "detail": "未提供 vault_id / vault_sources / vault_path"}],
        )

    vault_ids: list[int] = []
    run_ids: list[int] = []
    skipped: list[dict] = []

    for src in sources:
        try:
            # 解析 vault 实体
            if src["type"] == "vault_id":
                vault = await vault_repo.get_vault(session, int(src["value"]), user_id)
                if vault is None:
                    skipped.append({
                        "source": src["value"],
                        "reason": "vault_not_found",
                        "detail": f"vault_id={src['value']} 不存在或不属于当前用户",
                    })
                    continue
            else:
                vault = await _upsert_vault(session, user_id, src["source_type"], src["source_value"])

            vault_ids.append(vault.id)

            # 提交作业
            run = await vault_service.submit_sync(
                vault=vault,
                settings=settings,
                embed_profile_ref=req.embed_profile,
                mode=req.mode,
                dry_run=req.dry_run,
                prune=req.prune,
                force=req.force,
                filters=req.filters,
                trigger="manual",
            )
            run_ids.append(run.id)

        except AlreadyRunning as e:
            skipped.append({
                "source": src["value"],
                "reason": "already_running",
                "existing_run_id": e.existing_run_id,
            })
        except Exception as e:
            skipped.append({
                "source": src["value"],
                "reason": "submit_failed",
                "detail": str(e),
            })

    return IngestSubmitResponse(
        vault_ids=vault_ids,
        run_ids=run_ids,
        skipped=skipped,
    )
