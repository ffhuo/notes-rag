"""
app/mcp/server.py —— 将本项目的检索 / 问答能力封装为 MCP server，供 agent（WorkBuddy / OpenClaw 等）调用。

职责：
- 把 app/services 下的检索与问答编排，暴露为标准 MCP tools（search_notes / ask_notes / ingest_vault / list_vaults）。
- 支持两种传输：stdio（默认，agent 拉起子进程）与 Streamable HTTP（在 FastAPI 挂载 /mcp，供多 agent 共享）。
- 不直接实现 RAG 逻辑，全部复用 services 层，保证与 REST 路径逻辑单一来源。

关联文档：docs/design.md §14（Agent 接入方案）。

主要组件（建议你手写实现）：
- mcp：FastMCP / Server 实例，注册下方工具。
- search_notes(query, top_k, vault_id)：→ retrieval_service.retrieve
- ask_notes(question, vault_id, conversation_id)：→ chat_service.stream（流式）
- ingest_vault(vault_path, reindex)：→ ingest_service.scan
- list_vaults()：→ config / note_repo
- main()：stdio / http 两种传输入口（见文件底部）

个人用户注意：stdio 零端口最省事；http 模式仅监听 127.0.0.1，绝不暴露 0.0.0.0（见 §14.7）。
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

# 启用 MCP 前需 `uv sync`（pyproject 已声明 mcp>=1.2）。
# 这里用官方 SDK 的 FastMCP 高层封装；如需裸协议可改用 `from mcp.server import Server`。
from mcp.server.fastmcp import FastMCP

from app.core.config import get_settings  # 依赖注入获取配置
from app.services import chat_service, ingest_service, retrieval_service


# ──────────────────────────────────────────────
# MCP server 实例（stdio / http 共用）
# ──────────────────────────────────────────────
mcp = FastMCP("rag-as-api")


# ──────────────────────────────────────────────
# Tools：直接调用 services 层，不重写 RAG
# ──────────────────────────────────────────────
@mcp.tool()
async def search_notes(query: str, top_k: int = 5, vault_id: str | None = None) -> list[dict]:
    """在知识库中做语义检索，返回最相关的笔记片段及出处。

    参数:
        query: 查询文本
        top_k: 返回条数
        vault_id: 目标 vault（多 vault 时；单用户可省略）
    返回: [{file_path, title, content, score}, ...]
    """
    # TODO: 调用 retrieval_service.retrieve(query, top_k, threshold=...)
    # 若 vault_id 非空，需按 §6 隔离列过滤
    ...


@mcp.tool()
async def ask_notes(
    question: str,
    vault_id: str | None = None,
    conversation_id: str | None = None,
) -> AsyncIterator[str]:
    """基于知识库做检索增强问答，流式返回答案与引用。

    参数:
        question: 用户问题
        vault_id: 目标 vault（可选）
        conversation_id: 多轮对话上下文（可选）
    """
    # TODO: 调用 chat_service.stream(question, conversation_id, top_k)
    # 注意流式返回；保存已生成消息（见 §12 风险项）
    ...


@mcp.tool()
async def ingest_vault(vault_path: str | None = None, reindex: bool = False) -> dict:
    """扫描并索引指定 vault（或默认 vault），返回统计。

    参数:
        vault_path: vault 路径；省略则用配置中的默认 vault
        reindex: True 时清空旧索引重建
    """
    # TODO: 调用 ingest_service.scan(vault_path or settings.vault_path, reindex)
    ...


@mcp.tool()
async def list_vaults() -> list[dict]:
    """列出已配置 / 已索引的 vault。"""
    # TODO: 读取 config.vault_paths / note_repo 统计
    ...


# ──────────────────────────────────────────────
# 入口：stdio（默认）或 Streamable HTTP
# ──────────────────────────────────────────────
def main() -> None:
    """stdio 传输：agent 通过 mcp.json 的 command 拉起本进程。

    配置示例见 docs/design.md §14.5。
    """
    # FastMCP 默认以 stdio 运行；要启用 Streamable HTTP，见下方注释
    mcp.run(transport="stdio")
    # HTTP 模式（多 agent 共享）：mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
    # 注意：http 仅监听 127.0.0.1，绝不绑定 0.0.0.0（个人用户安全边界，见 §14.7）


if __name__ == "__main__":
    main()
