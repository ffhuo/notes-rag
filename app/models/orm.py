"""ORM 模型 — SQLAlchemy 表定义（用户 / vault / 笔记元数据 / 对话历史）。

能力：
- 定义 users / vaults / model_profiles / notes / chunks / conversations / messages / sync_runs 八张表
- users：多用户模式的账号（ENABLE_MULTIUSER=true 时启用，见 design.md §17.3）
- vaults：vault 成为 DB 实体，由前端配置（本地目录 / 上传 zip），见 §17.2 / §17.4
- model_profiles：多模型配置（LLM / Embedding 各可配多个，使用时可选），见 §18.1
- notes / chunks / conversations / messages 均带 user_id / vault_id 隔离列（单用户模式 user_id="default"）
- notes 携带变更判据字段（size_bytes / mtime_ns / content_hash），支撑增量同步
- sync_runs：每次同步 / 重建的运行记录（计数 / 失败清单 / 护栏拦截原因）
- 通过 vector_id 与向量库（Chroma）关联同一份片段

主要类：
- Base: DeclarativeBase 基类
- User: users 表（username 唯一，password_hash，is_admin）
- Vault: vaults 表（user_id 归属，source_type/source_value 来源，origin 配置来源，filters_json 摄取过滤）
- Note: notes 表（(vault_id, file_path) 复合唯一，记录标题 / 大小 / 纳秒 mtime / 内容摘要 / 索引时间）
- Chunk: chunks 表（note_id 外键，vector_id 唯一关联向量库）
- Conversation: conversations 表（vault_id 归属）
- Message: messages 表（conversation_id 外键，role/content/时间）
- SyncRun: sync_runs 表（同步运行记录：trigger/mode/计数/护栏原因/失败清单）

关联方案：docs/design.md §6（数据模型）、§17（前端 / Vault / 多用户）、§18（多模型管理）。
变更管理（增量 / 删除 / 改名对账）详见设计文档库 M03 §5.8–§5.12。
"""
import uuid

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import (
    String, Integer, Boolean, BigInteger, ForeignKey, DateTime, UniqueConstraint, func,
)


class Base(DeclarativeBase):
    pass


class User(Base):
    """用户表（多用户模式，ENABLE_MULTIUSER=true 时启用）。单用户模式不使用。

    uid: 对外唯一标识（UUID hex 字符串），JWT sub 和所有 user_id 外键均用它。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String, unique=True, default=lambda: uuid.uuid4().hex)
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class ModelProfile(Base):
    """模型配置表：允许用户配置多个 LLM / Embedding，使用时选择（见 design.md §18.1）。

    - kind：'llm'（对话/问答）或 'embed'（向量化）；两类各自独立解析默认项
    - name：用户内唯一的可读名（如 'qwen-max' / 'bge-m3-local'），请求里可用它做选择
    - provider：'openai'（OpenAI 兼容协议，覆盖 Qwen / vLLM / 本地服务等）；为将来非兼容协议预留
    - base_url / api_key / model：连接三元组；api_key 明文存库（个人自部署），见 §18.6 安全说明
    - params_json：附加参数 JSON（temperature / dim / max_tokens / timeout…）
    - is_default：该 kind 下的默认项；同一 (user_id, kind) 只允许一个 true
    - origin：'ui' = 前端/API 创建；'env' = 由 .env 种子注入（§18.4 种子规则）
    """

    __tablename__ = "model_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    kind: Mapped[str] = mapped_column(String)              # llm | embed
    name: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String, default="openai")
    base_url: Mapped[str] = mapped_column(String, default="")
    api_key: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String)
    params_json: Mapped[str] = mapped_column(String, default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    origin: Mapped[str] = mapped_column(String, default="ui")   # ui | env
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class Vault(Base):
    """vault 表：vault 作为 DB 实体，由前端配置（本地目录 / 上传 zip / git / 远程）。

    - user_id：归属用户（单用户模式为 "default"）；系统种子 vault 也归 "default"
    - source_type：local / uploaded / git / remote
    - source_value：local→绝对路径；uploaded→UPLOAD_DIR/<id>；git/remote→URL 或缓存目录
    - origin：配置来源，"ui" = 前端/API 创建（一期唯一来源）
             早期版本曾用 "env" 表示由 .env 种子注入，该机制已废弃（vault 完全由 DB/API/前端
             运行时配置，.env 不再提供种子）；保留列仅为兼容已入库历史数据，不再产生新 "env" 值
    - filters_json：该 vault 的摄取过滤（扩展名 / 排除目录 / include / exclude / max_file_size）
    """

    __tablename__ = "vaults"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    name: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)
    source_value: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String, default="ui")  # 一期恒为 "ui"（见上）
    filters_json: Mapped[str] = mapped_column(String, default="{}")
    # embedding 绑定：向量空间与模型强绑定，不能像 LLM 那样随时换（见 §18.2）
    embed_profile_id: Mapped[int] = mapped_column(Integer, nullable=True)   # 当前生效的 embedding 配置
    embed_indexed_profiles: Mapped[str] = mapped_column(String, default="[]")  # 已建过索引的 profile id（JSON 数组）
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    indexed_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)


class Note(Base):
    """笔记表：一个源文件一条。

    - file_path：**相对 vault 根的 POSIX 相对路径**（不是绝对路径）。绝对路径会让
      「vault 目录改名 / 搬家」被对账误判为「整库删除 + 整库新增」，白算全部 embedding。
    - 唯一约束为 **(vault_id, file_path)**：不同 vault 下的同名文件（README.md / index.md）
      互不覆盖；单列唯一会让变更对账的 known 集合失真。
    - 变更判据三字段（见 M03 §5.8）：
        · L1 快判：size_bytes + mtime_ns（遍历 stat 即得，零额外 IO）
        · L2 权威判：content_hash（仅 L1 不一致时计算，用于识别「时间戳变了但内容没变」）
    - last_seen_at：最后一次扫描「见到」本文件的时间；仅供 doctor 诊断，不参与判据。
    """

    __tablename__ = "notes"
    __table_args__ = (UniqueConstraint("vault_id", "file_path", name="uq_notes_vault_path"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id"))
    file_path: Mapped[str] = mapped_column(String)                        # 相对路径
    title: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)           # 判据 L1
    mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)          # 判据 L1（纳秒）
    content_hash: Mapped[str] = mapped_column(String, default="")         # 判据 L2
    indexed_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)


class SyncRun(Base):
    """作业记录表：既是变更管理的可观测载体，也是**异步任务的持久化载体**（M03 §5.11 / §5.13）。

    一次 sync / rebuild = 一个作业（run）。提交时 INSERT(queued)，后台协程推进 stage 与进度，
    收尾时写终态与计数。之所以「可观测」与「任务状态」共用一张表：二者一对一、同生命周期，
    拆表只会多一次 join（M03 ADR-13）。

    - trigger：谁触发的 —— manual（手动）/ schedule（定时）/ watch（文件监听）/
               startup（启动）/ cli / mcp
    - mode：sync（对账增量）| rebuild（全量重建）
    - dry_run：本次是「只算不写」的预览（作业停在 stage=plan_ready）
    - status：七态 —— queued / running 为进行中；success / partial（部分文件失败）为完成；
              **failed（程序异常）/ cancelled（用户主动停止）/ aborted（进程崩溃残留）**
              是三种语义不同的失败终态，排查时不可混淆（M03 §5.13.6）
    - 进度列：stage / total / processed / current_item / message / cancel_requested
              **total 为 NULL 表示该阶段总量不可知**（如 scan 阶段），前端进度条据此转「不确定态」
    - 计数列：adds / updates / moves / deletes / unchanged / failed_cnt
    - blocked_reason：删除护栏拦截原因 —— source_unavailable / scan_incomplete / over_ratio
      （见 M03 ADR-7：删除必须通过三道护栏，否则只增不删）
    - detail_json：失败文件清单 [{path, reason}] 或 dry_run 的计划快照；
      这是「为什么这个文件没被索引」的唯一可查来源
    - 保留策略：每 vault 只保留最近 N 条（SYNC_RUNS_KEEP，默认 50），超限按时间裁剪

    关键约束：本行必须在 asyncio.create_task 派发**之前**落库，否则进程在「返回 run_id」与
    「建 task」之间崩溃时，客户端会拿到一个永远查不到的 run_id（M03 §5.13.2）。
    业务逻辑（对账 / 护栏 / 进度推进 / 取消检查）由 run_service 与 sync_service 手写实现。
    """

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id"))
    trigger: Mapped[str] = mapped_column(String, default="manual")
    mode: Mapped[str] = mapped_column(String, default="sync")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String, default="queued")

    # ---- 进度（作业可视化，M03 §5.13.3 / §5.13.4）----
    stage: Mapped[str] = mapped_column(String, default="queued")
    #   probe | scan | diff | plan | plan_ready | index | prune | done
    total: Mapped[int] = mapped_column(Integer, nullable=True)
    #   NULL = 本阶段总工作量不可知（scan 阶段即如此）→ 前端进度条转「不确定态」，不硬编假分母
    processed: Mapped[int] = mapped_column(Integer, default=0)
    current_item: Mapped[str] = mapped_column(String, nullable=True)   # 当前处理的相对路径
    message: Mapped[str] = mapped_column(String, nullable=True)        # 如 "嵌入 120/480 分块"
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    #   取消是**协作式**的：本列只表示「已请求」，真正停止发生在文件边界（M03 ADR-14）

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


class Chunk(Base):
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
    embed_profile_id: Mapped[int] = mapped_column(Integer, nullable=True)  # 该分块由哪个 embedding 模型生成（§18.2）


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id"), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    user_id: Mapped[str] = mapped_column(String, default="default")
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
