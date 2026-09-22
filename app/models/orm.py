"""ORM 模型 — SQLAlchemy 表定义（用户 / vault / 笔记元数据 / 对话历史）。

能力：
- 定义 users / vaults / model_profiles / notes / chunks / conversations / messages 七张表
- users：多用户模式的账号（ENABLE_MULTIUSER=true 时启用，见 design.md §17.3）
- vaults：vault 成为 DB 实体，由前端配置（本地目录 / 上传 zip），见 §17.2 / §17.4
- model_profiles：多模型配置（LLM / Embedding 各可配多个，使用时可选），见 §18.1
- notes / chunks / conversations / messages 均带 user_id / vault_id 隔离列（单用户模式 user_id="default"）
- 通过 vector_id 与向量库（Chroma）关联同一份片段

主要类：
- Base: DeclarativeBase 基类
- User: users 表（username 唯一，password_hash，is_admin）
- Vault: vaults 表（user_id 归属，source_type/source_value 来源，origin 配置来源，filters_json 摄取过滤）
- Note: notes 表（file_path 唯一，记录标题 / 修改时间 / 索引时间）
- Chunk: chunks 表（note_id 外键，vector_id 唯一关联向量库）
- Conversation: conversations 表（vault_id 归属）
- Message: messages 表（conversation_id 外键，role/content/时间）

关联方案：docs/design.md §6（数据模型）、§17（前端 / Vault / 多用户）、§18（多模型管理）。
"""
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Float, Integer, Boolean, ForeignKey, DateTime, func


class Base(DeclarativeBase):
    pass


class User(Base):
    """用户表（多用户模式，ENABLE_MULTIUSER=true 时启用）。单用户模式不使用。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
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
    - origin：配置来源，"ui" = 前端/API 创建，"env" = 由 .env 的 VAULT_SOURCES 种子注入
             （仅用于前端展示与「是否可再次注入」判定，见 §17.2 种子规则）
    - filters_json：该 vault 的摄取过滤（扩展名 / 排除目录 / include / exclude / max_file_size）
    """

    __tablename__ = "vaults"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    name: Mapped[str] = mapped_column(String)
    source_type: Mapped[str] = mapped_column(String)
    source_value: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String, default="ui")  # ui | env
    filters_json: Mapped[str] = mapped_column(String, default="{}")
    # embedding 绑定：向量空间与模型强绑定，不能像 LLM 那样随时换（见 §18.2）
    embed_profile_id: Mapped[int] = mapped_column(Integer, nullable=True)   # 当前生效的 embedding 配置
    embed_indexed_profiles: Mapped[str] = mapped_column(String, default="[]")  # 已建过索引的 profile id（JSON 数组）
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    indexed_at: Mapped[DateTime] = mapped_column(DateTime, nullable=True)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    vault_id: Mapped[int] = mapped_column(ForeignKey("vaults.id"))
    file_path: Mapped[str] = mapped_column(String, unique=True)
    title: Mapped[str] = mapped_column(String)
    mtime: Mapped[float] = mapped_column(Float)
    indexed_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())


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
