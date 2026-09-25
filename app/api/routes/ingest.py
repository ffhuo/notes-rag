"""路由·摄取 — POST /api/v1/ingest（CLI / MCP 的入口，见 M03 §5.7）。

能力：
- 接收 vault_path / vault_sources / vault_id / rebuild / mode / dry_run / prune / force /
  filters / embed_profile
- **只做三件事**：解析入参 → 幂等 upsert 成 vault 实体 → 逐个 `run_service.submit` 提交作业
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

from app.api.deps import get_current_api_key
from app.models.schemas import IngestRequest, IngestSubmitResponse
from app.services import run_service, vault_service

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest", response_model=IngestSubmitResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest(
    req: IngestRequest,
    _: str = Depends(get_current_api_key),
) -> IngestSubmitResponse:
    """提交索引作业（202 = 已受理，不代表已完成）。

    实现步骤：
    1) 归一化源列表：vault_id（已存在）/ vault_sources / vault_path（兼容单源）
    2) 对每个源幂等 upsert 出 vault 实体（同 owner + 同 source_value 不重复建）
    3) 逐个 run_service.submit(...)；AlreadyRunning → 记入 skipped（reason="already_running"）
    4) 汇总返回 { vault_ids, run_ids, skipped }

    兼容字段 rebuild=True 等价 mode="rebuild"（旧调用方不感知作业模型也能工作）。
    """
    ...
