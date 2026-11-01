"""ORM·模型配置 — model_profiles 表（多模型管理，design.md §10 模块索引 M08）。"""
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, DateTime, func

from app.models.base import Base


class ModelProfile(Base):
    """模型配置表：允许用户配置多个模型种类，使用时选择。

    - kind：任务类型（llm / embed / asr / rerank），各自独立管理默认项
    - name：用户内唯一的可读名（如 'qwen-max' / 'bge-m3-local'）
    - provider：'openai'（OpenAI 兼容协议）；为将来非兼容协议预留
    - base_url / api_key / model：连接三元组
    - params_json：附加参数 JSON（temperature / dim / max_tokens / timeout…）
    - is_default：该 kind 下的默认项；同一 (user_id, kind) 只允许一个 true
    - origin：'ui' = 前端/API 创建；'env' = 由 .env 种子注入（已废弃）
    """

    __tablename__ = "model_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String, default="default")
    kind: Mapped[str] = mapped_column(String)              # llm | embed | asr | rerank
    name: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String, default="openai")
    base_url: Mapped[str] = mapped_column(String, default="")
    api_key: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String)
    params_json: Mapped[str] = mapped_column(String, default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    origin: Mapped[str] = mapped_column(String, default="ui")
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
