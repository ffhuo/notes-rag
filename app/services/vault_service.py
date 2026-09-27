"""业务·vault 管理 — 把「前端配置的 vault」解析为本地路径，并**提交作业**（M06 §5.3）。

本模块**不实现任何索引 / 对账逻辑**。对同步类操作它只做两件事：
    解析源为本机路径 → 调用 run_service.submit()
真正的执行、进度、取消全部在 M03 的作业链路上（run_service → sync_service → ingest_service）。

能力：
- 把 Vault（DB 实体）解析为本地目录路径：
  - local：直接返回 source_value（绝对路径）
  - uploaded：返回 UPLOAD_DIR/<vault_id>（上传时解压到的目录）
  - git / remote：一期不做在线拉取，缓存目录存在则用，否则抛 SourceUnavailable
- 接收上传的 vault 压缩包 → 解压到 UPLOAD_DIR/<vault_id>（防穿越 / 防炸弹）
- 提交同步作业（sync / rebuild 共用一条提交路径，差别只在 mode）

**vault 状态回写不在本模块**：`vault.embed_profile_id` / `embed_indexed_profiles` 的语义是
「**当前可检索**的 embedding」，是作业产物，由 run_service.execute 在 success / partial 时回写；
失败 / 取消保持原值（M06 ADR-9）。

关联方案：M06 §5.3 / §5.5；M03 §5.13；M08 §4；M10 §3。
"""
from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings as default_settings
from app.core.database import session_scope
from app.models import SyncRun, Vault
from app.models.schemas import IngestFilters
from app.services import model_service, run_service
from app.services.model_service import to_runtime

# 解压防护上限（一期固定值，与单文件 max_file_size 独立）
_MAX_ZIP_ENTRIES = 20_000
_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024  # 2GB 总解压体积


class SourceUnavailable(Exception):
    """vault 源不可达（路径不存在 / 上传目录缺失 / git 缓存未就绪）。

    抛出方是本模块（解析期止损），消费方是 sync 的护栏 1：**ABORT 整个 sync**。
    若把它降级成「空目录」，对账会得出「所有文件都被删了」，
    一次网络抖动就足以清空整个索引 —— 本项目最危险的失败模式（M03 ADR-7）。
    """


def resolve_local_path(vault: Vault, settings: Settings) -> Path:
    """由 source_type 解析出可索引的本地目录。不可达 → 抛 SourceUnavailable。

    - local：source_value 即绝对路径（必须存在且是目录）
    - uploaded：settings.upload_dir/<vault_id>
    - git / remote：一期不在线拉取，仅在缓存目录已存在时返回，否则明确报错
    绝不返回不存在的空目录。
    """
    source_type = (vault.source_type or "").lower()

    if source_type == "local":
        p = Path(vault.source_value).expanduser()
    elif source_type == "uploaded":
        # 与 save_upload 保持一致用绝对路径：避免 CWD 变化时指向别处
        p = (Path(settings.upload_dir) / str(vault.id)).resolve()
    elif source_type in ("git", "remote"):
        # 一期：不做 clone/pull。缓存目录由其他手段预置；缺失即明确失败。
        p = Path(settings.upload_dir) / f"{source_type}_{vault.id}"
        if not (p.exists() and p.is_dir()):
            raise SourceUnavailable(
                f"{source_type} 源暂不支持在线拉取，且本地缓存不存在：{p}"
            )
        return p
    else:
        raise SourceUnavailable(f"未知 source_type={vault.source_type!r}")

    if not p.exists() or not p.is_dir():
        raise SourceUnavailable(f"vault 源目录不存在或不是目录：{p}")
    return p


async def save_upload(vault_id: "int | str", file: Any, settings: Settings = default_settings) -> Path:
    """接收上传的 zip → 安全解压到 settings.upload_dir/<vault_id>，返回该目录（**绝对路径**）。

    返回值会被写进 vault.source_value，而 source_value 的语义是「绝对路径」（本地目录与
    目录树浏览端点都按绝对路径解析）。settings.upload_dir 默认是相对路径 `./data/uploads`，
    若原样落库，一旦进程 CWD 与建库时不同，浏览解压目录就会指向别处 —— 故此处统一 resolve。

    防护：
    - 只处理 zip（按文件名 / 魔数）；非 zip 抛 ValueError
    - 路径穿越：拒绝解析后逃逸目标目录的条目（含绝对路径与 .. ）
    - 解压炸弹：条目数 ≤ _MAX_ZIP_ENTRIES、累计解压体积 ≤ _MAX_UNCOMPRESSED_BYTES
    重复上传：先清空旧目录再解压（整包替换，保证与压缩包内容一致）。
    """
    data = await file.read()
    name = getattr(file, "filename", "") or ""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ValueError(f"仅支持 .zip 压缩包：{name!r}")

    target = (Path(settings.upload_dir) / str(vault_id)).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    target_resolved = target.resolve()
    total_bytes = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > _MAX_ZIP_ENTRIES:
            shutil.rmtree(target, ignore_errors=True)
            raise ValueError(f"压缩包条目数超限（>{_MAX_ZIP_ENTRIES}）")

        for info in infos:
            # 穿越防护：规范化后必须仍在目标目录内
            member_path = (target / info.filename).resolve()
            if target_resolved not in member_path.parents and member_path != target_resolved:
                shutil.rmtree(target, ignore_errors=True)
                raise ValueError(f"压缩包含非法路径（疑似穿越）：{info.filename!r}")

            if info.is_dir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue

            total_bytes += info.file_size
            if total_bytes > _MAX_UNCOMPRESSED_BYTES:
                shutil.rmtree(target, ignore_errors=True)
                raise ValueError("压缩包解压后总体积超限（疑似解压炸弹）")

            member_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(member_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

    return target


async def submit_sync(
    vault: Vault,
    settings: Settings = default_settings,
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
    1) 解析 embedding：ref（name 或 id）或当前默认 embed profile → runtime；
       一条 embed 配置都没有时抛 ModelNotConfigured，由路由层转 409
    2) 增量模式下做跨模型守卫 assert_embed_compatible；rebuild 允许换模型
    3) run_service.submit(...) —— 抢锁 / 落库(queued) / create_task / 返回 run

    本函数**不解析 local_path**（执行阶段才解析），提交不依赖源可达。
    """
    async with session_scope() as session:
        # 无任何 embed 配置 → ModelNotConfigured，路由层转 409 提示去「模型」页配置
        profile = await model_service.resolve_profile(
            session, settings, "embed", ref=embed_profile_ref, user_id=vault.user_id
        )
        runtime = to_runtime(profile)
        profile_id: "int | str" = profile.id

        # 跨模型守卫：只对「增量 sync」生效；换模型必须走 rebuild（M08 §2）
        if mode != "rebuild":
            model_service.assert_embed_compatible(vault, profile)

    return await run_service.submit(
        vault,
        mode=mode,
        dry_run=dry_run,
        prune=prune,
        force=force,
        filters=filters,
        embed_runtime=runtime,
        embed_profile_id=profile_id,
        trigger=trigger,
    )
