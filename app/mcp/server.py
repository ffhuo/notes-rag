"""app/mcp/server.py —— 把本项目的检索 / 问答能力封装成 MCP server，供 agent 调用。

职责：
- 把 services 层能力暴露为标准 MCP 工具（**一期只读**：search_notes / get_note /
  list_vaults / ask_notes），供 WorkBuddy / Trae / OpenClaw 等 agent 调用。
- 支持两种传输：
    * stdio —— agent 以子进程方式拉起（`python -m app.mcp.server`），零端口最省事；
    * Streamable HTTP —— 挂到主服务的 `/mcp`（与 REST 同端口同进程），供远程 agent 接入。
- 不实现 RAG 逻辑，全部复用 services，保证与 REST 路径逻辑单一来源。

鉴权（详见 app/mcp/auth.py）：
- stdio：启动时用 env `NOTES_RAG_API_KEY`（用户级 key）预先授权，解析失败即退出。
- Streamable HTTP：逐请求从 HTTP 头解析身份（`X-API-Key` 或 `Authorization: Bearer`），
  身份不跨请求复用。**工具内一律先解析身份再访问 services**，数据隔离由 services
  按 user_id 过滤保证，工具绝不自行放宽权限。

为什么一期不暴露 ingest_vault：MCP 是「请求-响应」模型，而本项目索引是异步作业，
agent 侧如何跟进（轮询 / 阻塞等待 / 只做只读）尚未定案，故暂缓（见 docs/mcp-guide.md §7）。

关联文档：docs/design.md §14（Agent 接入方案）、docs/mcp-guide.md（接入使用说明）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException
from loguru import logger
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from app.api.deps import resolve_embed_runtime
from app.core.config import settings
from app.core.database import session_scope
from app.mcp import auth as mcp_auth
from app.models import Vault
from app.repositories import note_repo, vault_repo
from app.services import (
    chat_service,
    model_service,
    retrieval_service,
    vault_service,
)
from app.services.model_service import (
    ModelNotConfigured,
    ModelNotFound,
    to_runtime,
)

# get_note 单篇正文上限：超过则引导 agent 改用 search_notes 取片段，避免一次灌爆上下文
_MAX_NOTE_BYTES = 1_000_000

_INSTRUCTIONS = """本服务是你可访问的个人知识库（notes-rag）。

使用约定：
- 用户问到「我的笔记 / 我的知识库 / 我的资料」时，先调用 search_notes 检索，
  再用检索到的真实片段回答，并注明来源 file_path。
- 需要整篇原文时用 get_note（先经 search_notes 或 list_vaults 确认路径）。
- 不确定有哪些库时先调用 list_vaults；多数场景可通过其返回的 vault_id 指定检索范围。
- search_notes / get_note 不消耗用户额度，可放心多次调用以补足上下文。
- 若提示「没有配置向量模型」或「vault 尚未建索引」，说明用户在 Web 端还需完成相应设置，
  请如实转告，不要编造笔记内容。"""


# ──────────────────────────────────────────────
# 内部辅助
# ──────────────────────────────────────────────
# 工具内一律抛 ToolError：SDK 只把 ToolError 的文案原样回给 agent，
# 其他异常会被抹成「Error executing tool xxx」（原文只留服务端日志），
# agent 就看不到「vault 尚未建索引」这类可自助排查的原因了。
async def _require_user_id(ctx: Context) -> str:
    """解析当前调用者身份；解析不出直接报错（fail closed，绝不回退到某个默认用户）。"""
    user_id = await mcp_auth.user_id_from_headers(ctx.headers)
    if user_id is None:
        raise ToolError(
            "鉴权失败：请在 MCP 请求头携带有效的用户级 API Key"
            "（X-API-Key: nr_…；可在 Web 端「设置 → API Keys」签发）"
        )
    return user_id


async def _resolve_vault(session, user_id: str, vault_id: int | None) -> Vault:
    """定位目标 vault：显式给的必须归属当前身份；未给则要求「唯一 vault」才自动选中。

    不自动「挑第一个」：多 vault 时静默选错库，agent 会把错误结果当事实回答给用户，
    比明确报错危险得多。
    """
    if vault_id is not None:
        vault = await vault_repo.get_vault(session, int(vault_id), user_id)
        if vault is None:
            raise ToolError(f"vault_id={vault_id} 不存在或不属于当前身份")
        return vault

    vaults = await vault_repo.list_vaults(session, user_id)
    if not vaults:
        raise ToolError(
            "当前身份下没有任何 vault：请先在 Web 端「Vaults」页添加知识库并完成一次同步"
        )
    if len(vaults) > 1:
        options = "、".join(f"{v.id}={v.name}" for v in vaults)
        raise ToolError(f"存在多个 vault，请显式指定 vault_id（可选：{options}）")
    return vaults[0]


async def _embed_runtime(session, user_id: str, vault: Vault):
    """解析检索用 embedding 运行时；把 deps 层的 HTTP 语义错误翻译成工具可读的报错。"""
    try:
        return await resolve_embed_runtime(session, user_id, vault)
    except HTTPException as e:
        raise ToolError(str(e.detail)) from e


async def _llm_runtime(session, user_id: str):
    """解析问答用 LLM 运行时（无 llm 配置时报错引导去「模型」页添加）。"""
    try:
        profile = await model_service.resolve_profile(
            session, "llm", ref=None, user_id=user_id
        )
    except ModelNotConfigured as e:
        raise ToolError("尚未配置 LLM：请到「模型」页新增一个 kind=llm 的配置") from e
    except ModelNotFound as e:
        raise ToolError(str(e)) from e
    return to_runtime(profile)


def _brief_source(src: dict) -> dict:
    """检索来源精简为「出处 + 相关度」，正文片段对 agent 通常冗余。"""
    return {
        "file_path": src.get("file_path", ""),
        "title": src.get("title", ""),
        "score": round(float(src.get("score") or 0.0), 4),
    }


# ──────────────────────────────────────────────
# Tools：只做编排，RAG 逻辑一律复用 services 层
# ──────────────────────────────────────────────
async def search_notes(
    ctx: Context,
    query: str,
    top_k: int = 5,
    vault_id: int | None = None,
) -> list[dict]:
    """在知识库中做语义检索，返回最相关的笔记片段及出处。

    什么时候用：用户问「我的笔记里关于 X 的内容」这类问题时，先用本工具取真实片段，
    再基于片段作答（不要凭记忆编造笔记内容）。

    参数:
        query: 查询文本（自然语言即可）
        top_k: 返回片段数上限（默认 5）
        vault_id: 目标知识库 id；只有在一个 vault 时可省略（多个 vault 时必填，见 list_vaults）

    返回: [{file_path, title, content, score, vault_id}, ...]，按相关度降序；无命中返回 []
    """
    user_id = await _require_user_id(ctx)
    if not query or not query.strip():
        raise ToolError("query 不能为空")
    top_k = max(1, min(int(top_k or 5), 50))

    async with session_scope() as session:
        vault = await _resolve_vault(session, user_id, vault_id)
        embed_runtime, embed_profile_id = await _embed_runtime(session, user_id, vault)
        hits = await retrieval_service.retrieve(
            query,
            top_k=top_k,
            vault_id=vault.id,
            embed_profile_id=embed_profile_id,
            embed_runtime=embed_runtime,
        )

    logger.info("MCP search_notes", user_id=user_id, vault_id=vault.id, hits=len(hits))
    return [
        {
            "file_path": h.file_path,
            "title": h.title,
            "content": h.content,
            "score": round(float(h.score), 4),
            "vault_id": vault.id,
        }
        for h in hits
    ]


async def get_note(
    ctx: Context,
    file_path: str,
    vault_id: int | None = None,
) -> dict:
    """读取整篇笔记原文（按相对 vault 根的路径）。

    什么时候用：已经知道确切路径、需要看全文时（路径可由 search_notes 结果或
    list_vaults 获得）。只想要相关片段时用 search_notes 更省上下文。

    参数:
        file_path: 相对 vault 根的 POSIX 路径，如 Interview/Golang/sync.md
        vault_id: 目标知识库 id；只有一个 vault 时可省略

    返回: {vault_id, file_path, title, size_bytes, content}
    """
    user_id = await _require_user_id(ctx)
    rel = (file_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        raise ToolError(
            "file_path 不能为空（相对 vault 根的路径，如 Interview/Golang/sync.md）"
        )

    async with session_scope() as session:
        vault = await _resolve_vault(session, user_id, vault_id)
        note = await note_repo.get_note_by_path(session, vault.id, rel)
        if note is None:
            raise ToolError(f"笔记不存在：{rel}（可先用 search_notes 检索确认路径）")
        try:
            root = vault_service.resolve_local_path(vault, settings)
        except vault_service.SourceUnavailable as e:
            raise ToolError(f"vault 源不可达：{e}") from e
        stored_path = note.file_path
        title = note.title

    # 路径安全：索引里的相对路径仍按不可信输入处理，解析后必须仍落在 vault 根内，
    # 否则 `../../etc/passwd` 之类可越权读盘
    root_resolved = root.resolve()
    target = (root_resolved / stored_path).resolve()
    if not target.is_relative_to(root_resolved):
        raise ToolError(f"非法路径：超出 vault 根目录（{stored_path}）")
    if not target.is_file():
        raise ToolError(f"文件已不在磁盘上：{stored_path}（源可能已变更，请重新同步索引）")

    size = await asyncio.to_thread(lambda: target.stat().st_size)
    if size > _MAX_NOTE_BYTES:
        raise ToolError(
            f"笔记过大（{size} 字节，上限 {_MAX_NOTE_BYTES}）：请改用 search_notes 检索片段"
        )
    content = await asyncio.to_thread(
        lambda: target.read_text(encoding="utf-8", errors="replace")
    )

    logger.info("MCP get_note", user_id=user_id, vault_id=vault.id, path=stored_path)
    return {
        "vault_id": vault.id,
        "file_path": stored_path,
        "title": title,
        "size_bytes": size,
        "content": content,
    }


async def list_vaults(ctx: Context) -> list[dict]:
    """列出当前身份下已配置的知识库（vault）及其索引状态。

    什么时候用：不确定有哪些库、需要 vault_id 来限定检索范围，或用户问
    「我有哪几个笔记库」时。

    返回: [{vault_id, name, source_type, note_count, indexed_at, embed_profile_id}, ...]
    """
    user_id = await _require_user_id(ctx)

    async with session_scope() as session:
        vaults = await vault_repo.list_vaults(session, user_id)
        # 笔记数逐库统计：vault 数量通常个位数，且本工具非热路径，取全量路径计数即可
        out = []
        for v in vaults:
            notes = await note_repo.list_note_paths(session, v.id)
            out.append(
                {
                    "vault_id": v.id,
                    "name": v.name,
                    "source_type": v.source_type,
                    "note_count": len(notes),
                    "indexed_at": v.indexed_at.isoformat() if v.indexed_at else None,
                    "embed_profile_id": v.embed_profile_id,
                }
            )

    logger.info("MCP list_vaults", user_id=user_id, count=len(out))
    return out


async def ask_notes(
    ctx: Context,
    question: str,
    vault_id: int | None = None,
    conversation_id: int | None = None,
    top_k: int = 5,
) -> dict:
    """基于知识库做检索增强问答，返回整合后的答案与引用来源。

    什么时候用：想让本服务自己完成「检索 + 组织答案」时。若你（agent）更擅长组织语言，
    建议改用 search_notes 取片段后自行作答 —— 那样更省 token，也更可控。

    参数:
        question: 用户问题
        vault_id: 目标知识库 id；只有一个 vault 时可省略
        conversation_id: 延续已有对话时传入（首次留空则新建）
        top_k: 检索片段数

    返回: {answer, sources: [{file_path, title, score}], conversation_id, vault_id}
    """
    user_id = await _require_user_id(ctx)
    if not question or not question.strip():
        raise ToolError("question 不能为空")
    top_k = max(1, min(int(top_k or 5), 50))

    answer_parts: list[str] = []
    sources: list[dict[str, Any]] = []
    conv_id: int | None = conversation_id

    async with session_scope() as session:
        vault = await _resolve_vault(session, user_id, vault_id)
        embed_runtime, embed_profile_id = await _embed_runtime(session, user_id, vault)
        llm_runtime = await _llm_runtime(session, user_id)

        # MCP 工具是请求-响应模型，这里把流式事件收集成完整答案后一次性返回
        async for event in chat_service.stream(
            question,
            session=session,
            user_id=user_id,
            conversation_id=conversation_id,
            top_k=top_k,
            vault_id=vault.id,
            embed_runtime=embed_runtime,
            embed_profile_id=embed_profile_id,
            llm_runtime=llm_runtime,
        ):
            kind = event.get("type")
            if kind == "token":
                answer_parts.append(str(event.get("data") or ""))
            elif kind == "sources":
                sources = event.get("data") or []
            elif kind == "done":
                conv_id = (event.get("data") or {}).get("conversation_id", conv_id)
            elif kind == "error":
                raise ToolError(f"问答失败：{event.get('data')}")

    logger.info("MCP ask_notes", user_id=user_id, vault_id=vault.id, sources=len(sources))
    return {
        "answer": "".join(answer_parts),
        "sources": [_brief_source(s) for s in sources],
        "conversation_id": conv_id,
        "vault_id": vault.id,
    }


# ──────────────────────────────────────────────
# server 构造与入口
# ──────────────────────────────────────────────
def build_server() -> MCPServer:
    """构造 MCP server 并注册全部工具。

    做成工厂而非直接写死模块级单例：MCP SDK 的 session manager 每个实例只能 run 一次，
    测试需要互不干扰的实例；生产侧复用下方模块级的 `mcp`。
    """
    server = MCPServer(
        "notes-rag",
        version=settings.version,
        instructions=_INSTRUCTIONS,
    )
    for fn in (search_notes, get_note, list_vaults, ask_notes):
        server.add_tool(fn)
    return server


# 模块级实例：app/main.py 挂载 HTTP 端点、`python -m app.mcp.server` 跑 stdio 都用它
mcp = build_server()


def build_http_app(server: MCPServer | None = None):
    """构造可挂到 FastAPI 的 Streamable HTTP 子应用（main.py 挂到 `/mcp`）。

    - `streamable_http_path="/"`：子应用自身再带一层 `/mcp` 路径的话，挂载后就变成
      `/mcp/mcp`，故置为根路径。
    - 关闭 DNS rebinding 保护：该保护要求显式配置 allowed_hosts，默认空列表会让
      **所有**请求 421（实测），而部署主机名/IP 因环境而异无法预设。本服务的边界由
      用户级 API Key 保证（浏览器不会自动携带自定义头，DNS rebinding 拿不到 key），
      且生产部署建议置于反向代理之后，可在那一层做 Host 白名单。
    """
    return (server or mcp).streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )


async def _serve_stdio() -> None:
    """stdio 启动流程：先解析身份（失败即退出），再进入协议循环。"""
    await mcp_auth.prime_stdio_identity()
    await mcp.run_stdio_async()


def main() -> None:
    """stdio 传输入口：agent 通过 MCP 配置的 command 拉起本模块。

    前置：env 提供 `NOTES_RAG_API_KEY`（用户级 key，Web 端「设置 → API Keys」签发）；
    单用户且未配全局 Key 的本机自用场景可省略（此时身份为 "default"）。
    """
    asyncio.run(_serve_stdio())


if __name__ == "__main__":
    main()
