"""API·依赖注入 — 向路由提供 config / db session / 鉴权 / RAG 组件。

能力：
- 注入配置（get_settings）
- 注入数据库会话（get_session，复用 core.database）
- 注入并校验 API Key（get_current_api_key，复用 core.security）
- 注入 RAG 组件（get_vector_store / get_embedder / get_llm，可选单例）

主要函数：
- get_settings() -> Settings
- get_session()（转发 core.database.get_session）
- get_current_api_key()（转发 core.security.get_current_api_key）
- get_vector_store() -> VectorStore: 懒加载持久化向量库
- get_embedder() / get_llm(): 懒加载客户端（或直接用模块函数）

关联方案：docs/design.md §1（依赖原则）、§2（api/deps.py）。
"""
from app.core.config import Settings  # 或 settings
from app.core.database import get_session
from app.core.security import get_current_api_key
from app.rag.vectorstore import VectorStore


def get_settings() -> Settings:
    ...


def get_vector_store() -> VectorStore:
    ...
