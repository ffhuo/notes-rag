"""数据访问·API Key — 用户级 API Key 的 CRUD（M06 §5.7）。

职责边界：只做 api_keys 表的原子读写；鉴权链的编排（先全局 key、
再用户级 key、再 JWT）在 core/security.get_current_user，不在这里。

事务边界由调用方掌握：本模块只 flush / 改对象，不 commit
（auth 路由与 security 鉴权链在各自流程末尾统一 commit）。

主要函数：
- async def create_api_key(session, user_id, name, key_hash, key_prefix) -> ApiKey
      落库一条新 key（明文由调用方生成并只在响应返回一次，此处只收哈希）
- async def list_api_keys(session, user_id) -> list[ApiKey]
      该用户的全部 key（含已撤销，便于前端展示与审计）
- async def get_api_key(session, user_id, key_id) -> ApiKey | None
      单条查询（撤销前先定位；user_id 过滤防越权）
- async def find_active_by_hash(session, key_hash) -> ApiKey | None
      **鉴权热路径**：按 sha256 查未撤销的 key。查不到 → 鉴权失败。
      命中后由调用方负责节流更新 last_used_at（touch_api_key）
- async def touch_api_key(session, key_id) -> None
      更新 last_used_at。**必须节流**（如距上次 > 60s 才写），
      否则每个 agent 请求都产生一次写放大（SQLite 本地可承受，但没必要）
- async def revoke_api_key(session, user_id, key_id) -> bool
      软删除：revoked_at 置当前时间。返回是否找到（未找到 → 404）

关联方案：M06 §5.7（用户级 API Key）、M02 §5.x（api_keys 表）。
"""
from datetime import UTC, datetime
from typing import List, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey

# last_used_at 节流阈值（秒）：距上次写入不足该值就跳过，避免鉴权热路径每次请求都写库
_TOUCH_INTERVAL_SECONDS = 60


async def create_api_key(
    session: AsyncSession,
    user_id: str,
    name: str,
    key_hash: str,
    key_prefix: str,
) -> ApiKey:
    row = ApiKey(user_id=user_id, name=name, key_hash=key_hash, key_prefix=key_prefix)
    session.add(row)
    # flush（而非 commit）：让调用方掌握事务边界，同时尽早暴露 key_hash 唯一冲突
    await session.flush()
    return row


async def list_api_keys(session: AsyncSession, user_id: str) -> List[ApiKey]:
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.id.desc())     # 新建的排在前面；按 id 而非 created_at，同秒创建也稳定
    )
    return list(result.scalars().all())


async def get_api_key(
    session: AsyncSession, user_id: str, key_id: int
) -> Optional[ApiKey]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def find_active_by_hash(
    session: AsyncSession, key_hash: str
) -> Optional[ApiKey]:
    # 仅返回 revoked_at IS NULL 的行；命中行是否真的可用（用户存在等）由鉴权链判定
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    )
    return result.scalar_one_or_none()


async def touch_api_key(session: AsyncSession, key_id: int) -> None:
    # 节流策略见 docstring：实现时先读 last_used_at 比较，超阈值才 UPDATE
    row = await session.get(ApiKey, key_id)
    if row is None:
        return
    # server_default 的 CURRENT_TIMESTAMP 在 SQLite 里是 UTC，这里保持同口径的 naive UTC，
    # 否则与库中值相减会得到错误的间隔
    now = datetime.now(UTC).replace(tzinfo=None)
    if (
        row.last_used_at is not None
        and (now - row.last_used_at).total_seconds() < _TOUCH_INTERVAL_SECONDS
    ):
        return
    row.last_used_at = now


async def revoke_api_key(session: AsyncSession, user_id: str, key_id: int) -> bool:
    # COALESCE：重复撤销保留首次撤销时间（幂等且不覆盖审计信息）
    result = await session.execute(
        update(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.user_id == user_id)
        .values(revoked_at=func.coalesce(ApiKey.revoked_at, func.now()))
        .execution_options(synchronize_session=False)
    )
    return bool(result.rowcount)
