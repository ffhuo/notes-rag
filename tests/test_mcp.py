"""MCP 接入 —— 鉴权、工具暴露与只读工具行为。

覆盖：
- 工具清单：4 个只读工具、不含 ingest_vault；Context 是注入参数，不应进入入参 schema
- HTTP 鉴权：无凭据拒绝、有效用户级 key 通过、无效 key 拒绝
- list_vaults / get_note 的正常路径，以及**路径穿越防护**（越出 vault 根必须拒绝）
- stdio 预先授权：有效 key 解析出 user_id，无效 key fail fast（SystemExit）

关联方案：M09（agent-mcp）§5.2 / §5.3 / §5.7；docs/mcp-guide.md。
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx2
import pytest
from fastapi import FastAPI
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.core import database
from app.core.config import settings
from app.mcp import auth as mcp_auth
from app.mcp.server import build_http_app, build_server
from app.models.api_key import generate_api_key, hash_api_key
from app.repositories import api_key_repo, note_repo, vault_repo


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """临时 SQLite：建表 → 用例 → 关闭引擎（与 test_api_key_repo 同做法）。"""
    monkeypatch.setattr(settings, "sqlite_path", str(tmp_path / "test.db"))
    await database.close_database_engine()
    await database.create_database_engine()
    await database.init_db()
    yield
    await database.close_database_engine()


@asynccontextmanager
async def _session(headers: dict[str, str] | None = None):
    """起一个真实 ASGI 链路的 Streamable HTTP 客户端会话（走完整 MCP 协议）。

    每个用例新建一套 server + app：MCP SDK 的 session manager 每个实例只能 run 一次，
    复用实例会让第二个用例直接报 RuntimeError。
    """
    server = build_server()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 与 app/main.py 一致：Mount 不会自动跑子应用 lifespan，需手动启动会话管理器
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp", build_http_app(server))

    async with lifespan(app):
        client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://127.0.0.1",
            headers=headers or {},
        )
        async with streamable_http_client(
            "http://127.0.0.1/mcp/", http_client=client
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def _payload(res) -> object:
    """工具返回体：优先取结构化结果，否则解析 TextContent 里的 JSON。

    MCP 的结构化输出要求顶层是对象，返回 list 时 SDK 会包一层 `{"result": [...]}`，
    这里统一拆掉，方便断言真实返回。
    """
    data = getattr(res, "structured_content", None)
    if data is None:
        data = json.loads(res.content[0].text)
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


async def _make_key(user_id: str = "u1", name: str = "agent") -> str:
    raw = generate_api_key()
    async with database.session_scope() as session:
        await api_key_repo.create_api_key(
            session,
            user_id=user_id,
            name=name,
            key_hash=hash_api_key(raw),
            key_prefix=raw[:11],
        )
    return raw


async def _make_vault(user_id: str = "u1", root=None, name: str = "notes") -> int:
    async with database.session_scope() as session:
        vault = await vault_repo.create_vault(
            session,
            user_id=user_id,
            name=name,
            source_type="local",
            source_value=str(root),
        )
        return vault.id


async def _add_note(vault_id: int, rel_path: str, *, user_id: str = "u1") -> None:
    async with database.session_scope() as session:
        await note_repo.upsert_note(
            session,
            vault_id=vault_id,
            rel_path=rel_path,
            title=rel_path,
            size_bytes=1,
            mtime_ns=1,
            content_hash="h",
            user_id=user_id,
        )


def _require_auth(monkeypatch) -> None:
    """把环境切成「已配全局 Key」的多用户语义，使鉴权链真正生效。"""
    monkeypatch.setattr(settings, "api_key", "global-test-key")
    monkeypatch.setattr(settings, "enable_multiuser", False)


# ──────────────────────────────────────────────
# 工具暴露
# ──────────────────────────────────────────────
async def test_exposes_only_readonly_tools(db):
    async with _session() as s:
        tools = (await s.list_tools()).tools

    assert {t.name for t in tools} == {"search_notes", "get_note", "list_vaults", "ask_notes"}
    for t in tools:
        props = (t.input_schema or {}).get("properties", {})
        # Context 是框架注入的，不能出现在 agent 可见的入参里
        assert "ctx" not in props


# ──────────────────────────────────────────────
# 鉴权
# ──────────────────────────────────────────────
async def test_rejects_missing_and_invalid_key(db, monkeypatch):
    _require_auth(monkeypatch)
    await _make_vault()

    async with _session() as s:
        res = await s.call_tool("list_vaults", {})
    assert res.is_error
    assert "鉴权失败" in res.content[0].text

    async with _session(headers={"X-API-Key": "nr_not-exists"}) as s:
        res = await s.call_tool("list_vaults", {})
    assert res.is_error
    assert "鉴权失败" in res.content[0].text


async def test_valid_user_key_is_isolated_by_user(db, monkeypatch):
    """用户级 key 决定身份：只能看到自己的 vault（越权隔离的端到端验证）。"""
    _require_auth(monkeypatch)
    mine = await _make_vault(user_id="u1", name="mine")
    await _make_vault(user_id="u2", name="other")
    raw = await _make_key("u1")

    async with _session(headers={"X-API-Key": raw}) as s:
        res = await s.call_tool("list_vaults", {})
    assert not res.is_error
    rows = _payload(res)
    assert [r["vault_id"] for r in rows] == [mine]
    assert rows[0]["name"] == "mine"


async def test_revoked_key_is_rejected(db, monkeypatch):
    _require_auth(monkeypatch)
    await _make_vault(user_id="u1")
    raw = await _make_key("u1")

    async with database.session_scope() as session:
        row = await api_key_repo.find_active_by_hash(session, hash_api_key(raw))
        await api_key_repo.revoke_api_key(session, "u1", row.id)

    async with _session(headers={"X-API-Key": raw}) as s:
        res = await s.call_tool("list_vaults", {})
    assert res.is_error


# ──────────────────────────────────────────────
# 只读工具行为
# ──────────────────────────────────────────────
async def test_list_vaults_reports_note_count(db, monkeypatch, tmp_path):
    _require_auth(monkeypatch)
    root = tmp_path / "vault"
    root.mkdir()
    vault_id = await _make_vault(root=root)
    await _add_note(vault_id, "a.md")
    await _add_note(vault_id, "b.md")
    raw = await _make_key("u1")

    async with _session(headers={"X-API-Key": raw}) as s:
        rows = _payload(await s.call_tool("list_vaults", {}))

    assert rows[0]["note_count"] == 2
    assert rows[0]["indexed_at"] is None      # 没建过索引 → 未索引状态可被 agent 读出


async def test_get_note_returns_content(db, monkeypatch, tmp_path):
    _require_auth(monkeypatch)
    root = tmp_path / "vault"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.md").write_text("正文内容 ABC", encoding="utf-8")
    vault_id = await _make_vault(root=root)
    await _add_note(vault_id, "sub/a.md")
    raw = await _make_key("u1")

    async with _session(headers={"X-API-Key": raw}) as s:
        res = await s.call_tool("get_note", {"file_path": "sub/a.md"})

    assert not res.is_error
    data = _payload(res)
    assert data["file_path"] == "sub/a.md"
    assert data["content"] == "正文内容 ABC"


async def test_get_note_blocks_path_traversal(db, monkeypatch, tmp_path):
    """索引里的相对路径仍是不可信输入：越出 vault 根必须拒绝，不能读库外文件。"""
    _require_auth(monkeypatch)
    root = tmp_path / "vault"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET", encoding="utf-8")
    vault_id = await _make_vault(root=root)
    # 构造一条越界 notes 行（正常索引不会产生，但代码不能依赖「数据一定干净」）
    await _add_note(vault_id, "../secret.txt")
    raw = await _make_key("u1")

    async with _session(headers={"X-API-Key": raw}) as s:
        res = await s.call_tool("get_note", {"file_path": "../secret.txt"})

    assert res.is_error
    assert "非法路径" in res.content[0].text


async def test_get_note_reports_unknown_path(db, monkeypatch, tmp_path):
    _require_auth(monkeypatch)
    root = tmp_path / "vault"
    root.mkdir()
    vault_id = await _make_vault(root=root)
    raw = await _make_key("u1")

    async with _session(headers={"X-API-Key": raw}) as s:
        res = await s.call_tool("get_note", {"file_path": "not-indexed.md"})

    assert res.is_error
    assert "笔记不存在" in res.content[0].text


async def test_search_notes_maps_hits_to_plain_dicts(db, monkeypatch, tmp_path):
    """search_notes 只做编排：embed 解析与 retrieve 被替换后，返回结构应稳定。"""
    _require_auth(monkeypatch)
    root = tmp_path / "vault"
    root.mkdir()
    await _make_vault(root=root)
    raw = await _make_key("u1")

    async def fake_embed(session, user_id, vault):
        return None, 7

    async def fake_retrieve(query, **kwargs):
        from app.models.schemas import ChunkHit

        return [
            ChunkHit(
                note_id="1",
                file_path="a.md",
                title="A",
                content="片段内容",
                score=0.8712,
                images=[],
            )
        ]

    monkeypatch.setattr("app.mcp.server.resolve_embed_runtime", fake_embed)
    monkeypatch.setattr("app.mcp.server.retrieval_service.retrieve", fake_retrieve)

    async with _session(headers={"X-API-Key": raw}) as s:
        res = await s.call_tool("search_notes", {"query": "片段"})

    assert not res.is_error
    hits = _payload(res)
    assert hits == [
        {"file_path": "a.md", "title": "A", "content": "片段内容", "score": 0.8712, "vault_id": 1}
    ]


async def test_search_notes_requires_single_vault_when_unspecified(db, monkeypatch, tmp_path):
    """多 vault 且未指定时明确报错 —— 静默挑一个库会让 agent 把错库结果当事实。"""
    _require_auth(monkeypatch)
    root = tmp_path / "vault"
    root.mkdir()
    await _make_vault(root=root, name="one")
    await _make_vault(root=root, name="two")
    raw = await _make_key("u1")

    async with _session(headers={"X-API-Key": raw}) as s:
        res = await s.call_tool("search_notes", {"query": "x"})

    assert res.is_error
    assert "存在多个 vault" in res.content[0].text


# ──────────────────────────────────────────────
# stdio 预先授权
# ──────────────────────────────────────────────
async def test_stdio_identity_resolves_and_fails_fast(db, monkeypatch):
    monkeypatch.setattr(mcp_auth, "_STDIO_USER_ID", None)
    _require_auth(monkeypatch)

    raw = await _make_key("u1")
    monkeypatch.setenv("NOTES_RAG_API_KEY", raw)
    assert await mcp_auth.prime_stdio_identity() == "u1"

    # 无效 key → 启动即退出（fail fast，agent 立刻看到配置错误）
    monkeypatch.setattr(mcp_auth, "_STDIO_USER_ID", None)
    monkeypatch.setenv("NOTES_RAG_API_KEY", "nr_revoked")
    with pytest.raises(SystemExit):
        await mcp_auth.prime_stdio_identity()

    # 缺 key 且非免鉴权模式 → 同样 fail fast
    monkeypatch.setattr(mcp_auth, "_STDIO_USER_ID", None)
    monkeypatch.delenv("NOTES_RAG_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        await mcp_auth.prime_stdio_identity()


async def test_stdio_identity_falls_back_to_default_when_open_access(db, monkeypatch):
    """单用户且未配全局 Key（本机自用）时，无凭据回退 "default"，与 REST 一致。"""
    monkeypatch.setattr(mcp_auth, "_STDIO_USER_ID", None)
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "enable_multiuser", False)
    monkeypatch.delenv("NOTES_RAG_API_KEY", raising=False)

    assert await mcp_auth.prime_stdio_identity() == "default"
