"""ORM·API Key — api_keys 表（用户级 API Key，供 agent / 第三方接入鉴权）。

设计要点（M06 §5.7）：
- **库中只存 SHA-256 哈希，绝不存明文** —— 明文仅在创建响应里出现一次，
  丢失只能撤销重建（与 GitHub token / OpenAI key 同一策略）。
- key 归属用户（user_id = users.uid）：agent 持 key 调用时，数据隔离与
  该用户完全一致（vaults / model_profiles / sync_runs 均按 user_id 过滤）。
- key_prefix（前 8 字符）供前端列表识别，不含足够熵、无法反推出 key。
- 撤销 = 软删除（revoked_at 置时间），记录保留便于审计。
"""
import uuid

from sqlalchemy import String, DateTime, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ApiKey(Base):
    """用户级 API Key 表。

    key_hash: sha256(明文 key) 的 hex 字符串，唯一 —— 鉴权时按此查找。
    key_prefix: "nr_" + 明文前 8 字符，仅用于列表展示识别。
    user_id: 所属用户（users.uid）；agent 以此身份访问，隔离与该用户一致。
    revoked_at: 非空即已撤销（软删除，鉴权直接视为无效）。
    last_used_at: 最近一次通过该 key 鉴权的时间（节流更新，非每次请求都写）。
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.uid", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String, default="")  # 用户备注，如 "workbuddy"
    key_hash: Mapped[str] = mapped_column(String, unique=True)
    key_prefix: Mapped[str] = mapped_column(String)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        # 鉴权热路径：按 key_hash 查（唯一索引已覆盖）；此索引服务「按用户列表」
        Index("ix_api_keys_user_id", "user_id"),
    )


def generate_api_key() -> str:
    """生成明文 key：`nr_` + 32 位 hex（128 bit 熵）。

    纯函数（无副作用），供创建端点调用；明文只在创建响应返回一次。
    """
    return f"nr_{uuid.uuid4().hex}"


def hash_api_key(raw: str) -> str:
    """明文 key → sha256 hex。鉴权链用它查 api_keys.key_hash。"""
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()
