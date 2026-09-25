"""业务·vault 管理 — 把「前端配置的 vault」解析为本地路径，并**提交作业**（M06 §5.3）。

本模块**不实现任何索引 / 对账逻辑**。对同步类操作它只做两件事：
    解析源为本机路径 → 调用 run_service.submit()
真正的执行、进度、取消全部在 M03 的作业链路上（run_service → sync_service → ingest_service）。

能力：
- 把 Vault（DB 实体）解析为本地目录路径：
  - local：直接返回 source_value（绝对路径）
  - uploaded：返回 UPLOAD_DIR/<vault_id>（上传时解压到的目录）
  - git / remote：首次 clone/pull 或下载到缓存目录，返回该目录
- 接收上传的 vault 压缩包 → 解压到 UPLOAD_DIR/<vault_id>
- 提交同步作业（sync / reindex 共用一条提交路径，差别只在 mode）

主要函数：
- def resolve_local_path(vault, settings) -> Path
      源不可达时抛 SourceUnavailable，由 sync 的护栏 1 转成 ABORT
      （绝不把「源不可达」当成「文件全被删了」——那会清空整个索引）
- async def save_upload(vault_id, file, settings) -> Path
- async def submit_sync(vault, embed_profile_ref=None, mode="sync", dry_run=False,
                        prune=True, force=False, filters=None, trigger="manual") -> SyncRun
      1) 解析 embedding（M08 resolve_profile）+ assert_embed_compatible
      2) run_service.submit(...) —— 抢锁 / 落库(queued) / create_task / 返回 run
      抢不到锁时 run_service 抛 AlreadyRunning，由路由层转 409（M06 ADR-8）

**vault 状态回写不在本模块**：`vault.embed_profile_id` / `embed_indexed_profiles` 的语义是
「**当前可检索**的 embedding」，因此它们是**作业产物的一部分**，由 run_service.execute 在
收尾且状态为 success / partial 时回写；失败 / 取消保持原值。
若在提交时就回写，一个失败的 rebuild 会让 vault 谎称「已用 bge-m3 建好索引」，
而 collection 里没有任何对应向量 —— 检索会**静默返回空结果**（M06 ADR-9）。

关联方案：M06 §5.3（提交语义）/ §5.5（API 契约）；M03 §5.13（作业化执行）；
         M08 §4（embedding 解析与回退）；M10 §3（uploaded / git / remote 的拉取策略）。
"""
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.models.orm import SyncRun, Vault
from app.models.schemas import IngestFilters


class SourceUnavailable(Exception):
    """vault 源不可达（路径不存在 / git 拉取失败 / 网络挂载掉线）。

    抛出方是本模块（解析期止损），消费方是 sync 的护栏 1：**ABORT 整个 sync**。
    若把它降级成「空目录」，对账会得出「所有文件都被删了」的结论，
    一次网络抖动就足以清空整个索引 —— 这是本项目最危险的失败模式（M03 ADR-7）。
    """


def resolve_local_path(vault: Vault, settings: Settings) -> Path:
    """由 source_type 解析出可索引的本地目录。

    - local：source_value 即绝对路径
    - uploaded：settings.upload_dir/<vault_id>
    - git / remote：拉取 / 更新到缓存目录后返回该目录
    不可达 → 抛 SourceUnavailable（**不要**返回一个空目录）。
    """
    ...


async def save_upload(vault_id: str, file: Any, settings: Settings) -> Path:
    # 接收 multipart 的 .zip → 解压到 settings.upload_dir/<vault_id>
    # 需防 zip 路径穿越（../ 逃逸解压目录）与解压炸弹（条目数 / 总解压体积上限）
    ...


async def submit_sync(
    vault: Vault,
    settings: Settings,
    embed_profile_ref: str | None = None,
    mode: str = "sync",
    dry_run: bool = False,
    prune: bool = True,
    force: bool = False,
    filters: "IngestFilters | None" = None,
    trigger: str = "manual",
) -> SyncRun:
    """提交一次同步作业，返回刚落库的作业记录（路由随即回 202 + run_id）。

    步骤：
    1) 解析 embedding 配置：embed_profile_ref（name 或 id）或当前默认 embed profile
       → model_service.to_runtime() 得 embed_runtime
    2) assert_embed_compatible(vault, profile)：跨模型增量会让同一 collection
       混入两种向量空间的向量 —— 不一致必须走 mode="rebuild"（M08 §2）
    3) run_service.submit(vault, mode, dry_run, prune, force, filters, embed_runtime, trigger)

    注意：本函数**不解析 local_path** —— 那是执行阶段的事（sync_service 内），
    提交只需 vault 实体；否则「提交」就会依赖源可达，把异步提交变成同步校验。
    """
    ...
