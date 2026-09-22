"""Pydantic 模型 — 请求与响应的数据契约（DTO）。

能力：
- 定义 /ingest、/search、/chat 接口的请求体
- 定义检索命中、对话事件等响应体
- 提供类型校验，配合 FastAPI 自动生成 OpenAPI 文档

主要类：
- IngestRequest: { vault_path: str, rebuild: bool = False }
- IngestResponse: { scanned: int, indexed_chunks: int, elapsed_ms: int }
- SearchRequest: { query: str, top_k: int = 5, threshold: float = 0.0 }
- ChunkHit: { note_id, file_path, title, content, score }  # 单条检索命中
- SearchResponse: { hits: list[ChunkHit] }
- ChatRequest: { query: str, conversation_id: str | None, top_k: int = 5 }
- ChatEvent: { type: "token"|"sources"|"done", ... }  # SSE 事件载荷

关联方案：docs/design.md §5（API 设计）、§10（手写 TODO 地图）。
"""
from pydantic import BaseModel


class IngestRequest(BaseModel):
    vault_path: str
    rebuild: bool = False


class IngestResponse(BaseModel):
    scanned: int
    indexed_chunks: int
    elapsed_ms: int


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    threshold: float = 0.0


class ChunkHit(BaseModel):
    note_id: str
    file_path: str
    title: str
    content: str
    score: float


class SearchResponse(BaseModel):
    hits: list[ChunkHit]


class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    top_k: int = 5
