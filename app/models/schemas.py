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
- ModelRuntime / ModelProfileCreate / ModelProfileUpdate / ModelProfileOut：多模型配置（§18）
  - ModelRuntime 是解析后的运行时配置，rag 层只依赖它，不反向依赖 service / DB

关联方案：docs/design.md §5（API 设计）、§10（手写 TODO 地图）、§18（多模型管理）。
"""
from typing import Any, List

from pydantic import BaseModel, SecretStr


class IngestFilters(BaseModel):
    """摄取过滤条件（可选，覆盖配置默认值，见 docs/design.md §16.3）。

    - include: 相对 vault 根的路径 glob 白名单；为空 = 不限
    - exclude: 相对 vault 根的路径 glob 黑名单；优先于 include
    - exts:    扩展名白名单，覆盖 config.ingest_exts
    - max_file_size: 文件字节上限；超过则跳过，None = 不限
    """

    include: List[str] | None = None
    exclude: List[str] | None = None
    exts: List[str] | None = None
    max_file_size: int | None = None


class IngestRequest(BaseModel):
    vault_path: str | None = None           # 兼容单 vault（等价于 local:<path>）
    vault_sources: List[str] | None = None  # 或直接传多源（覆盖 config）
    vault_id: str | None = None             # 或指定已存在的 vault（前端走 vaults + reindex，见 §17.2）
    rebuild: bool = False
    filters: IngestFilters | None = None    # 文件/文件夹过滤（见 docs/design.md §16）
    # 用哪个 embedding 配置建索引（name 或 id）；留空 = 当前默认 embed profile
    # 注意：换 embedding 会写入新的向量集合，同一 vault 可并存多份索引（见 §18.2）
    embed_profile: str | None = None


class IngestResponse(BaseModel):
    scanned: int
    indexed_chunks: int
    elapsed_ms: int


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    threshold: float = 0.0
    vault_id: str | None = None
    # 不提供 embed_profile：检索必须用「建索引时那个」embedding，否则向量空间不兼容（见 §18.2）。
    # 想换 embedding → 先对该 vault 重新 ingest，再检索。


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
    vault_id: str | None = None
    # 选择用哪个 LLM 配置（name 或 id）；留空 = 当前默认 llm profile。
    # LLM 无状态耦合，可每次请求自由切换（见 §18.2）
    llm_profile: str | None = None


# ===== 多模型管理（见 docs/design.md §18）=====
class ModelRuntime(BaseModel):
    """解析后的运行时模型配置 —— rag 层（embedder / llm_client）唯一依赖的模型对象。

    由 model_service.to_runtime(profile) 从 ModelProfile 解析得到：
    已应用「端点/密钥回退」与默认参数，rag 层不再关心 DB、用户默认、.env 等概念。
    """

    kind: str                      # llm | embed
    name: str                      # profile 名，便于日志与追踪
    base_url: str
    api_key: SecretStr
    model: str
    params: dict[str, Any] = {}


class ModelProfileCreate(BaseModel):
    """新建一个模型配置（LLM 或 Embedding）。"""
    kind: str                                   # llm | embed
    name: str                                   # 用户内唯一，如 'qwen-max' / 'bge-m3-local'
    model: str                                  # 模型标识，如 gpt-4o-mini / text-embedding-3-small
    provider: str = "openai"                    # OpenAI 兼容协议（Qwen / vLLM / 本地服务同）
    base_url: str = ""                          # 留空 = 回退 .env 的 LLM_BASE_URL / EMBED_BASE_URL
    api_key: str = ""                           # 留空 = 回退 .env 的 LLM_API_KEY / EMBED_API_KEY
    params: dict[str, Any] = {}                 # temperature / dim / max_tokens / timeout …
    set_default: bool = False                   # 是否同时设为该 kind 的默认项


class ModelProfileUpdate(BaseModel):
    """局部更新模型配置；未提供的字段保持不变。"""
    name: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None
    set_default: bool | None = None


class ModelProfileOut(BaseModel):
    """模型配置出参 —— 注意：api_key 永不返回，只给脱敏后的掩码。"""
    id: int
    kind: str
    name: str
    provider: str
    base_url: str
    model: str
    params: dict[str, Any] = {}
    is_default: bool = False
    enabled: bool = True
    origin: str = "ui"                # ui | env
    api_key_masked: str = ""          # 如 'sk-ab****yz'；未配置则为空串


class ModelTestResult(BaseModel):
    """连通性测试结果（POST /models/{id}/test 或 /models/test 试连未保存的配置）。"""
    ok: bool
    model: str
    elapsed_ms: int = 0
    error: str | None = None
    detail: str = ""                  # 例如返回维度（embed）或首块回复（llm）


# ===== Vault（前端配置，见 docs/design.md §17.2）=====
class VaultCreate(BaseModel):
    """新建 vault：本地目录（填 source_value 路径）或上传（source_type=uploaded，文件走 multipart）。"""
    name: str
    source_type: str                       # local / uploaded / git / remote
    source_value: str | None = None        # local→绝对路径；git/remote→URL；uploaded 由文件决定
    filters: "IngestFilters | None" = None  # 该 vault 的摄取过滤（§16.3）


class VaultOut(BaseModel):
    id: int
    user_id: str
    name: str
    source_type: str
    source_value: str
    origin: str = "ui"                     # ui = 前端/API 创建；env = .env 种子注入（§17.2）
    indexed_at: str | None = None


# ===== 多用户鉴权（ENABLE_MULTIUSER=true，见 docs/design.md §17.3）=====
class UserCreate(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
