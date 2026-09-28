"""API Key 仓储层 — 锁定 500 回归根因（占位实现导致 list 返回 None）。

背景：`api_key_repo` 曾整文件为 `...` 占位，函数隐式返回 None，
`GET /api/v1/auth/api-keys` 在 `for r in rows` 处抛
`TypeError: 'NoneType' object is not iterable`（500）。

本文件把仓储契约与事务边界（只 flush/改对象，不 commit）固化成断言。
关联方案：M06 §5.7（用户级 API Key）、M02 §5.x（api_keys 表）。
"""
from datetime import UTC, datetime, timedelta

import pytest

from app.api.routes.auth import list_api_keys as list_api_keys_endpoint
from app.core import database
from app.core.config import settings
from app.models import ApiKey
from app.models.api_key import generate_api_key, hash_api_key
from app.repositories import api_key_repo


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """临时 SQLite：建表 → 用例 → 关闭引擎（避免全局引擎在用例间串库）。"""
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "test.db"))
    await database.close_database_engine()
    await database.create_database_engine()
    await database.init_db()
    yield
    await database.close_database_engine()


async def _create(user_id: str = "u1", name: str = "k") -> tuple[int, str]:
    """造一条 key，返回 (id, 明文)。明文即调用的真实凭据，供哈希命中用例使用。"""
    raw = generate_api_key()
    async with database.session_scope() as session:
        row = await api_key_repo.create_api_key(
            session,
            user_id=user_id,
            name=name,
            key_hash=hash_api_key(raw),
            key_prefix=raw[:11],
        )
        return row.id, raw


async def _get(key_id: int) -> ApiKey:
    async with database.session_scope() as session:
        return await session.get(ApiKey, key_id)


@pytest.mark.asyncio
async def test_create_returns_row_with_id(db):
    """create 后对象立即可用（id 已由 flush 生成），调用方才敢 commit + refresh。"""
    key_id, raw = await _create()
    assert key_id > 0
    row = await _get(key_id)
    assert row.key_hash == hash_api_key(raw)
    assert row.key_prefix == raw[:11]
    assert row.revoked_at is None
    assert row.last_used_at is None


@pytest.mark.asyncio
async def test_list_returns_list_not_none(db):
    """回归点：空结果必须是 []（而非 None），否则调用方的 for 直接 500。"""
    async with database.session_scope() as session:
        assert await api_key_repo.list_api_keys(session, "nobody") == []

    first, _ = await _create(name="a")
    second, _ = await _create(name="b")

    async with database.session_scope() as session:
        rows = await api_key_repo.list_api_keys(session, "u1")
    assert [r.id for r in rows] == [second, first]  # 新建的排在前面


@pytest.mark.asyncio
async def test_list_isolated_by_user(db):
    mine, _ = await _create(user_id="u1")
    await _create(user_id="u2")

    async with database.session_scope() as session:
        assert [r.id for r in await api_key_repo.list_api_keys(session, "u1")] == [mine]


@pytest.mark.asyncio
async def test_get_and_find_active_by_hash(db):
    key_id, raw = await _create()

    async with database.session_scope() as session:
        assert (await api_key_repo.get_api_key(session, "u1", key_id)).id == key_id
        # 越权：别人的 key 一律查不到，调用方据此返回 404
        assert await api_key_repo.get_api_key(session, "u2", key_id) is None
        assert await api_key_repo.find_active_by_hash(session, hash_api_key(raw)) is not None
        assert await api_key_repo.find_active_by_hash(session, hash_api_key("nr_bogus")) is None

    async with database.session_scope() as session:
        await api_key_repo.revoke_api_key(session, "u1", key_id)

    # 撤销后鉴权必须立即失效（软删除的语义）
    async with database.session_scope() as session:
        assert await api_key_repo.find_active_by_hash(session, hash_api_key(raw)) is None


@pytest.mark.asyncio
async def test_touch_throttled_within_window(db):
    """鉴权热路径的写放大保护：窗口内不写、超窗口才写。"""
    key_id, _ = await _create()

    async with database.session_scope() as session:
        await api_key_repo.touch_api_key(session, key_id)
    first = (await _get(key_id)).last_used_at
    assert first is not None

    # 窗口内：再次 touch 不改变已记录时间
    async with database.session_scope() as session:
        await api_key_repo.touch_api_key(session, key_id)
    assert (await _get(key_id)).last_used_at == first

    # 超过阈值：更新为新时间
    old = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=120)
    async with database.session_scope() as session:
        row = await session.get(ApiKey, key_id)
        row.last_used_at = old

    async with database.session_scope() as session:
        await api_key_repo.touch_api_key(session, key_id)
    assert (await _get(key_id)).last_used_at > old

    # 不存在的 key 静默返回（鉴权链已确保存在，防御性要求不抛异常）
    async with database.session_scope() as session:
        await api_key_repo.touch_api_key(session, 999999)


@pytest.mark.asyncio
async def test_revoke_idempotent_and_isolated(db):
    key_id, _ = await _create(user_id="u1")

    # 越权撤销：返回 False（端点据此 404），且不得改动任何行
    async with database.session_scope() as session:
        assert await api_key_repo.revoke_api_key(session, "u2", key_id) is False

    async with database.session_scope() as session:
        assert await api_key_repo.revoke_api_key(session, "u1", key_id) is True

    # 重复撤销保留首次撤销时间（审计信息不被覆盖）
    stamp = datetime(2020, 1, 1)
    async with database.session_scope() as session:
        row = await session.get(ApiKey, key_id)
        row.revoked_at = stamp

    async with database.session_scope() as session:
        assert await api_key_repo.revoke_api_key(session, "u1", key_id) is True
    assert (await _get(key_id)).revoked_at == stamp


@pytest.mark.asyncio
async def test_endpoint_list_api_keys_does_not_crash(db):
    """直击日志中的崩溃点：端点函数对「无 key」必须返回 []，建 key 后能列出。"""
    async with database.session_scope() as session:
        assert await list_api_keys_endpoint(user_id="default", session=session) == []

    raw = generate_api_key()
    async with database.session_scope() as session:
        await api_key_repo.create_api_key(
            session,
            user_id="default",
            name="agent",
            key_hash=hash_api_key(raw),
            key_prefix=raw[:11],
        )

    async with database.session_scope() as session:
        out = await list_api_keys_endpoint(user_id="default", session=session)
    assert len(out) == 1
    assert out[0].name == "agent"
    assert not hasattr(out[0], "key")  # 响应模型永不含明文
