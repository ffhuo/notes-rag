"""ORM·Vault — vaults / notes / chunks / sync_runs 表。

vault 是 DB 实体，由前端配置（本地目录 / 上传 zip），见 design.md §17.2 / §17.4。
notes 携带变更判据字段，支撑增量同步，见 M03 §5.8。
sync_runs 是作业记录表，见 M03 §5.11 / §5.13。
"""
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String, Integer, Boolean, BigInteger, ForeignKey, DateTime, UniqueConstraint, func,
)

from app.models.base import Base


class Vault(Base):
    """vault 表：vault 作为 DB 实体，由前端配置。

    - user_id：归属用户（单用户模式为 "default"）
    - source_type：local / uploaded / git / remote
    - source_value：local→绝对路径；uploaded→UPLOAD_DIR/<id>
    - filters_json：摄取过滤（扩展名 / 排除目录 / max_file_size）
    - embed_profile_id：当前生效的 embedding 配置（§18.2）
    - embed_indexed_profiles：已建过索引的 profile id（JSON 数组）
    """

    __tablename__ = "vaults"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    name: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)
    source_value: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String, default="ui")
    filters_json: Mapped[str] = mapped_column(String, default="{}")
    embed_profile_id: Mapped[int] = mapped_column(Integer, nullable=True)
    embed_indexed_profiles: Mapped[str] = mapped_column(String, default="[]")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    indexed_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)


class Note(Base):
    """笔记表：一个源文件一条。

    - file_path：**相对 vault 根的 POSIX 相对路径**（不是绝对路径）
    - 唯一约束为 **(vault_id, file_path)**：不同 vault 下同名文件互不覆盖
    - 变更判据三字段：L1 快判 size_bytes + mtime_ns；L2 权威判 content_hash
    - last_seen_at：仅供 doctor 诊断，不参与判据
    """

    __tablename__ = "notes"
    __table_args__ = (UniqueConstraint("vault_id", "file_path", name="uq_notes_vault_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id"))
    file_path: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    content_hash: Mapped[str] = mapped_column(String, default="")
    indexed_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)


class Chunk(Base):
    """分块表：notes 的子表，通过 vector_id 与 Chroma 向量库关联。"""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id"))
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"))
    idx: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(String)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    vector_id: Mapped[str] = mapped_column(String, unique=True)
    embed_profile_id: Mapped[int] = mapped_column(Integer, nullable=True)


class SyncRun(Base):
    """作业记录表：一次 sync / rebuild = 一个作业（run）。

    - trigger：manual / schedule / watch / startup / cli / mcp
    - mode：sync（对账增量）| rebuild（全量重建）
    - status：queued / running / success / partial / failed / cancelled / aborted
    - 进度列：stage / total / processed / current_item / message / cancel_requested
    - 计数列：adds / updates / moves / deletes / unchanged / failed_cnt
    - blocked_reason：删除护栏拦截原因（source_unavailable / scan_incomplete / over_ratio）
    - detail_json：失败文件清单 [{path, reason}] 或 dry_run 的计划快照
    """

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id"))
    trigger: Mapped[str] = mapped_column(String, default="manual")
    mode: Mapped[str] = mapped_column(String, default="sync")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="queued")

    # 进度
    stage: Mapped[str] = mapped_column(String, default="queued")
    total: Mapped[int] = mapped_column(Integer, nullable=True)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    current_item: Mapped[str] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(String, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    # 计数
    adds: Mapped[int] = mapped_column(Integer, default=0)
    updates: Mapped[int] = mapped_column(Integer, default=0)
    moves: Mapped[int] = mapped_column(Integer, default=0)
    deletes: Mapped[int] = mapped_column(Integer, default=0)
    unchanged: Mapped[int] = mapped_column(Integer, default=0)
    failed_cnt: Mapped[int] = mapped_column(Integer, default=0)

    embed_profile_id: Mapped[int] = mapped_column(Integer, nullable=True)
    blocked_reason: Mapped[str] = mapped_column(String, nullable=True)
    error: Mapped[str] = mapped_column(String, nullable=True)
    detail_json: Mapped[str] = mapped_column(String, default="{}")
    started_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
