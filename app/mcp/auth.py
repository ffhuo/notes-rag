"""app/mcp/auth.py —— MCP 接入的身份解析（stdio 预先授权 / Streamable HTTP 逐请求）。

为什么单独成文件：server.py 只管「暴露哪些工具」，身份从哪来、怎么校验是另一件事。
MCP 不走 FastAPI 依赖链，无法直接复用 get_current_user，但**必须与它同源** ——
所以这里只做「从通道取凭据 → 交给 core.security.resolve_user_id」，不重写判定规则。

两种传输的身份来源（M06 §5.7 / M09 §5.2）：
- stdio：进程内直调，没有 HTTP 头。启动时读 env `NOTES_RAG_API_KEY`（用户级 key，
  Web 端「设置 → API Keys」签发），解析出 user_id 后缓存，进程内所有调用共用该身份。
  解析失败**直接退出**（fail fast）——让 agent 立刻看到配置错误，
  而不是在第一次调用时收到一堆「查不到数据」的假象。
- Streamable HTTP：每个请求各带凭据（`X-API-Key` 用户级 key，或 `Authorization: Bearer`），
  逐请求解析，身份**不跨请求复用** —— 同一进程可能被多个 agent 共用，
  缓存身份会让后到的调用者继承前一个人的权限（越权）。

安全边界：凭据一律经 sha256 查 api_keys 表，与 REST 完全同一条链；
用户级 key 只决定「是谁」，数据隔离由 services 层按 user_id 过滤保证，
工具内部**绝不**自行放宽权限。
"""
from __future__ import annotations

import os
from typing import Mapping

from loguru import logger

from app.core.database import init_db, session_scope
from app.core.security import resolve_user_id

# stdio 进程级身份缓存：仅 stdio 传输使用（HTTP 传输逐请求解析，不读它）
_STDIO_USER_ID: str | None = None


async def prime_stdio_identity() -> str:
    """stdio 启动时解析并缓存身份；无法确定身份则 SystemExit（fail fast）。

    调用时机：`python -m app.mcp.server` 启动期，早于任何 tool 调用。
    """
    global _STDIO_USER_ID

    raw = (os.getenv("NOTES_RAG_API_KEY") or "").strip()
    # stdio 是独立进程，可能先于主服务首次启动：确保库与表已就绪再查 key
    await init_db()

    async with session_scope() as session:
        # 有 key 就走常规鉴权链；无 key 时 resolve_user_id 仅在「单用户且未配全局 Key」
        # 的免鉴权模式下返回 "default"，其余情况返回 None（→ 这里判为配置缺失）
        user_id = await resolve_user_id(session, x_api_key=raw or None)

    if user_id is None:
        if raw:
            raise SystemExit(
                "NOTES_RAG_API_KEY 无效或已撤销。请在 Web 端「设置 → API Keys」"
                "重新签发（nr_ 开头），更新 agent 的 MCP 配置后重启。"
            )
        raise SystemExit(
            "未提供 NOTES_RAG_API_KEY，且当前不是「单用户免鉴权」模式，无法确定身份。"
            "请在 MCP 配置的 env 中设置 NOTES_RAG_API_KEY（Web 端「设置 → API Keys」签发）。"
        )

    _STDIO_USER_ID = user_id
    logger.info("MCP stdio 身份已就绪", user_id=user_id)
    return user_id


async def user_id_from_headers(headers: Mapping[str, str] | None) -> str | None:
    """按当前请求头解析 user_id；识别不出返回 None（由调用方转成工具体报错）。

    headers 为 None / 空（stdio 传输，或 HTTP 传输未携带头）时回退 stdio 预先授权身份。
    """
    if not headers:
        return _STDIO_USER_ID

    # 统一小写：Starlette 的 Headers 大小写不敏感，但普通 dict 不是，这里不赌调用方类型
    lowered = {str(k).lower(): v for k, v in dict(headers).items()}
    async with session_scope() as session:
        return await resolve_user_id(
            session,
            x_api_key=lowered.get("x-api-key"),
            authorization=lowered.get("authorization"),
        )
