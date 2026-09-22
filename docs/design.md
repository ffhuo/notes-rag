# 开发方案设计 — notes-rag

> 本文给出架构、分层职责、API 草稿、数据模型、RAG 管线与**手写 TODO 地图**。
> 所有 `.py` 业务逻辑由你手写实现；本仓库只提供目录骨架与本文。
> 配合 [需求清单与范围边界](requirements.md)。

## 1. 架构总览

分层架构，依赖方向自上而下（api → services → repositories / rag → core / models）：

```
Client (curl / 前端 SPA / Obsidian 插件 / Agent)
   │  HTTP (JSON / SSE)
   ▼
app/api/          路由层：接收请求、校验、调 service、组装响应，不含业务逻辑
   │
   ▼
app/services/     业务层：编排 ingest / retrieval / chat 流程
   ├─────────────► app/repositories/   数据访问：SQLite 读写（笔记元数据、对话）
   └─────────────► app/rag/            RAG 管线：chunker / embedder / vectorstore / llm_client
   │
   ▼
app/core/         横切：config / security / database 连接
app/models/       Pydantic schemas + ORM 定义
```

**依赖原则**
- 路由层不写业务逻辑；service 不碰 HTTP；repository 不碰 RAG；rag 不碰 FastAPI。
- 依赖通过 FastAPI `Depends` 注入（config、db session、clients）。

## 2. 目录结构与职责（手写地图总览）

```
app/
  main.py                # FastAPI 实例、生命周期、挂载路由、CORS、异常处理器        ← 手写
  api/
    deps.py              # 依赖注入：get_config / get_db / get_current_api_key / get_current_user / get_clients
    routes/
      ingest.py          # POST /api/v1/ingest
      search.py          # POST /api/v1/search
      chat.py            # POST /api/v1/chat (SSE 流式)
      health.py          # GET /healthz
      vaults.py          # 新增：GET/POST/DELETE /api/v1/vaults + reindex（前端配置 vault，见 §17.2）
      auth.py            # 新增：register/login/me（多用户模式，见 §17.3）
      models.py          # 新增：多模型 CRUD / 设默认 / 试连（见 §18.5）
  core/
    config.py            # Settings（pydantic-settings）读取 .env
    security.py          # API Key / JWT 校验
    database.py          # SQLite 引擎 / session / 建表
  models/
    schemas.py           # 请求 / 响应 Pydantic 模型（含 Vault / User / Token）
    orm.py               # SQLAlchemy 表：users / vaults / notes / chunks / conversations / messages（含 user_id/vault_id 隔离列）
  repositories/
    note_repo.py         # 笔记与分块元数据 CRUD
    conversation_repo.py # 对话与消息 CRUD
    vault_repo.py        # 新增：vault / user CRUD（见 §17.4）
  services/
    ingest_service.py    # 扫描→解析→分块→embedding→入库 编排
    retrieval_service.py # 查询→embedding→向量检索→组装上下文
    chat_service.py      # retrieval + LLM 流式生成 + 历史
    vault_service.py     # 新增：vault 解析为本地路径 / 上传解压 / reindex 编排（见 §17.2）
    model_service.py     # 新增：多模型解析（三级优先级）/ 构造客户端 / embedding 一致性守卫（见 §18）
  rag/
    chunker.py           # Markdown 切分策略
    embedder.py          # 文本→向量（OpenAI 兼容 embedding，async）
    vectorstore.py       # Chroma 封装：add / query / reset
    llm_client.py        # LLM 调用（chat.completions.create, stream=True）
  mcp/
    server.py             # 新增：MCP server（stdio / Streamable HTTP），把 services 封装成 tools ← 手写
  static/                # 新增：构建后的前端静态产物（由 frontend/ 构建产出，gitignore）
  parsers/               # 新增：多格式文件解析层（见 §16；一期仅 md/txt，其余预留）
    base.py              # DocumentParser 抽象基类 + ParsedDocument 数据结构
    registry.py          # 按扩展名路由 parser（register / get_parser）
    markdown.py          # Markdown 解析（一期实现）
    text.py              # 纯文本 txt 解析（一期实现）
    pdf.py               # PDF 解析（预留，依赖 pymupdf，可选安装）
    docx.py              # Word 解析（预留，依赖 python-docx，可选安装）
    excel.py             # Excel 解析（预留，依赖 openpyxl，可选安装）
tests/
  conftest.py, test_ingest.py, test_search.py, test_chat.py, test_security.py, test_vault.py, test_auth.py
scripts/
  init_db.py             # 建表脚本（也可在 database.py 内 create_all）
frontend/               # 新增：Vue 3 + Vite SPA 源码（见 §17.1），build → app/static
deploy/                  # 部署模板（见 design.md §15 / §17.6）
  Dockerfile             # 多阶段：node 构建前端 → python:3.12-slim + uv 镜像（见 §17.6）
  docker-compose.yml     # 服务 + 数据卷 + 反向代理（可选）
  nginx.conf.example     # 反向代理 + TLS 终止示例（注释说明）
```

## 3. 技术选型与理由

| 组件 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | 异步原生、Pydantic 校验、自动 OpenAPI 文档，练手+日常都香。 |
| 配置 | pydantic-settings | 配置与 schema 统一，类型安全读取 `.env`。 |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite | 元数据/历史持久化，练习 ORM + async session。 |
| 向量库 | Chroma（chromadb） | 本地持久化、零部署、API 简单；后期可换 pgvector。 |
| LLM（对话） | openai SDK（兼容） | `llm_base_url` / `llm_api_key` / `llm_model`，换模型只改配置。 |
| Embedding（向量化） | openai SDK（兼容） | `embed_base_url` / `embed_api_key` / `embed_model`；默认回退 LLM 同款端点/密钥，也可独立指向 BGE-M3 / 本地服务等。 |
| 服务器 | Uvicorn | ASGI 服务器。 |
| 部署 | Docker（python:3.12-slim 镜像 + uv） | 本地运行与服务端部署共用同一镜像；数据卷持久化 Chroma / SQLite（见 §15）。 |
| 反向代理 | Nginx / Caddy（可选，生产） | 终止 TLS、HTTP→HTTPS 跳转、限流，保护 `0.0.0.0` 端口（见 §15.4）。 |
| 重试/日志 | tenacity / rich（可选） | LLM 调用重试、日志美化。 |

## 4. 数据流与时序

### 4.1 Ingest
```
POST /ingest
  → ingest_service.scan(vault_sources, filters?)        # filters 见 §16.3（一期可留空走配置默认）
  → 应用过滤：跳过排除目录 → 扩展名白名单 → include/exclude glob 匹配
  → 对每个命中文件：按扩展名路由 parser（app/parsers/*，见 §16.2）→ 提取纯文本 + 元数据
  → chunker.split（md 用 split_markdown 保留标题面包屑；其余格式用 split_text 通用切分）
  → embedder.embed(chunks) → vectorstore.add(ids, vectors, metadatas)
  → note_repo.upsert(note, chunks)
  → 返回 { scanned, indexed_chunks, elapsed_ms }
```
MVP 同步返回汇总；进阶用 `BackgroundTasks`（不强制）。
> 文件类型与过滤的完整设计见 §16。v0.1 一期只实现 `.md` / `.txt`，PDF / Word / Excel 解析已预留接口（§16.1 类型矩阵），后续启用可选依赖即可。

### 4.2 Search
```
POST /search { query, top_k, threshold }
  → retrieval_service.retrieve(query, top_k, threshold)
  → embedder.embed(query) → vectorstore.query(vector, top_k)
  → 按 threshold 过滤 → 组装候选（含来源/相似度）
  → 返回 List[ChunkHit]
```

### 4.3 Chat（SSE 流式）
```
POST /chat { query, conversation_id?, top_k }
  → chat_service.stream(query, history)
  → retrieval_service.retrieve(query)
  → 拼 system prompt + 上下文片段 + history
  → llm_client.stream(...) → yield 增量 token
  → 结束：conversation_repo.save(conv, messages) + 回传 sources
```
前端用 `fetch` 读 stream 或 `EventSource` 接收 `text/event-stream`。

## 5. API 设计（草稿）

```
POST /api/v1/ingest
  body: { "vault_path": str, "rebuild": bool = false, "embed_profile": str|null }
  resp: { "scanned": int, "indexed_chunks": int, "elapsed_ms": int }

POST /api/v1/search
  body: { "query": str, "top_k": int = 5, "threshold": float = 0.0, "vault_id": str|null }
  resp: { "hits": [ { "note_id", "file_path", "title", "content", "score" } ] }
  # 注：故意不暴露 embed_profile —— 检索必须用建索引时那个模型（§18.2）

POST /api/v1/chat
  body: { "query": str, "conversation_id": str | null, "top_k": int = 5,
          "vault_id": str | null, "llm_profile": str | null }
  resp: text/event-stream (SSE)
    data: {"type":"token","text":"..."}
    data: {"type":"sources","items":[{"file_path","title","score"}]}
    data: {"type":"done"}

GET /healthz  → { "status": "ok" }

# —— Vault 管理（前端配置，均需鉴权，见 §17.2）——
GET    /api/v1/vaults              # 列出当前用户的 vault
POST   /api/v1/vaults              # JSON 建库：{ name, source_type: local|git|remote, source_value }
POST   /api/v1/vaults/upload       # multipart 上传：name + file=.zip（source_type=uploaded）
                                   # 注：FastAPI 同端点不能混 JSON body 与 UploadFile，故上传单列
GET    /api/v1/vaults/{id}         # 详情
DELETE /api/v1/vaults/{id}         # 删除（同时清该 vault 的索引与分块记录）
POST   /api/v1/vaults/{id}/reindex # 触发重建索引（BackgroundTasks 可选）
                                   # ?embed_profile=<name|id> 换 embedding 重建（§18.2）

# —— 多模型管理（见 §18.5）——
GET    /api/v1/models?kind=llm|embed   # 列表（密钥仅返回掩码）
POST   /api/v1/models                  # 新建
POST   /api/v1/models/test             # 试连未保存的配置
GET    /api/v1/models/{id}
PATCH  /api/v1/models/{id}
DELETE /api/v1/models/{id}             # 被 vault 引用则返回 409
POST   /api/v1/models/{id}/default     # 设为该 kind 默认项
POST   /api/v1/models/{id}/test        # 试连已保存的配置

# —— 多用户鉴权（ENABLE_MULTIUSER=true 时启用，见 §17.3）——
POST   /api/v1/auth/register       # { username, password } → { user_id, username }
POST   /api/v1/auth/login          # { username, password } → { access_token, token_type }
GET    /api/v1/auth/me             # 返回当前用户（调试/前端取身份）
```
> `/ingest` 仍保留，供命令行 / MCP 直接传 `vault_sources`；前端走「vaults + reindex」，不直接调 `/ingest`。
**鉴权**：受保护接口 Header `X-API-Key: <key>`（或 Bearer JWT）。`/healthz` 免鉴权。
**版本前缀**：所有业务接口挂 `/api/v1`。

## 6. 数据模型

**SQLite 表（SQLAlchemy ORM，见 models/orm.py）**
```sql
users(id PK, username UNIQUE, password_hash, is_admin, created_at)        -- 新增（§17.3）
vaults(id PK, user_id, name, source_type, source_value,
       filters_json, created_at, indexed_at)                              -- 新增（§17.2/§17.4）
notes(id PK, user_id, vault_id, file_path UNIQUE, title, mtime, indexed_at)   -- +user_id/vault_id
chunks(id PK, user_id, vault_id, note_id FK, idx, content,
       char_start, char_end, vector_id UNIQUE)                            -- +user_id/vault_id
conversations(id PK, user_id, vault_id, created_at)                        -- +user_id/vault_id
messages(id PK, conversation_id FK, user_id, role, content, created_at)    -- +user_id
```

**向量库（Chroma）collection = "notes"**
- `ids` = chunk 的 `vector_id`
- `embeddings` = embedder 输出
- `metadatas` = `{ note_id, file_path, title, chunk_idx }`

> 注意：embedding 维度必须与向量库一致；换 embedding 模型必须重建索引。

## 7. RAG 管线设计

- **分块（chunker）**：
  - `split_markdown(text, max_chars)`：按 Markdown 标题层级 + 长度上限（~800 字）滑动切分；保留标题面包屑作为上下文前缀，**仅用于 `.md`**（提升检索相关性）。
  - `split_text(text, max_chars)`（新增·通用）：对 `.txt` / `.pdf` / `.docx` / `.xlsx` 等非 md 内容，按长度上限 + 段落边界滑动切分，**不含**标题面包屑。所有 parser 统一输出纯文本，再交给 `split_text`（见 §16.2 解析器约定）。
  - 长度上限建议 ~800 字 / ~200 token，重叠窗口避免句子被切断。
- **嵌入（embedder）**：text-embedding 兼容模型；批量 embedding 控并发与限速。
- **检索（vectorstore）**：余弦相似度 Top-K；`threshold` 过滤低分噪声。
- **Prompt 模板**：system 说明「只依据 `<context>` 回答，笔记里没有就直说不知道」；user = 上下文片段 + 问题。
- **流式（llm_client）**：`stream=True`，逐 token yield；结束时回传 `sources`。
- **防幻觉**：要求引用来源；禁止编造 vault 外知识（写入 system prompt）。

> 向量库选型、Embedding 模型选择、RAG 检索方略（hybrid 检索 / rerank / 分块细节 / 评估）的详细对比与可抄示例，见 [向量库·Embedding·RAG 方略详解](vector-rag-embedding.md)；本文 §7 是其骨架，该文档是细化与选型依据。

## 8. 配置与安全

- `.env` 字段（LLM 与 Embedding **分开配置**）：
  - 对话 / 问答：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`
  - 文本向量化：`EMBED_BASE_URL` / `EMBED_API_KEY` / `EMBED_MODEL`
  - 其余：`VAULT_SOURCES` / `CHROMA_DIR` / `SQLITE_PATH` / `API_KEY` / `CORS_ORIGINS` / `HOST` / `PORT` / `PUBLIC_BASE_URL`
  - 多用户与前端（§17）：`ENABLE_MULTIUSER`（默认 false）/ `JWT_SECRET`（多用户必填）/ `UPLOAD_DIR`（上传 vault 解压目录，默认 `./data/uploads`）/ `UI_ENABLED`（默认 true，挂载 `app/static` 前端）
- **Embedding 配置回退**：`EMBED_BASE_URL` / `EMBED_API_KEY` 留空时，自动回退到 LLM 的 `LLM_BASE_URL` / `LLM_API_KEY`（多数 OpenAI 兼容服务两者共用，如 Qwen、本地 vLLM）。仅当 embedding 用独立服务（如本地 BGE-M3、不同供应商）时才需显式填。代码层用 `Settings.get_embed_base_url()` / `get_embed_api_key()` 取生效值。
- **vault 来源 `VAULT_SOURCES`**：支持「本地引用」与「远程导入」两类（详见 §15.3）：
  - `local:/abs/path/to/vault` — 本机目录直接引用（最常用，零拷贝）。
  - `git:https://.../vault.git` — 克隆远程 git 仓库到本地缓存再索引（适合把远端 vault 自动同步进来）。
  - `http(s)://.../vault.zip` 或 `http(s)://.../notes/` — 远程目录 / 压缩包拉取（进阶）。
  - 兼容旧字段 `VAULT_PATH`（单 vault 本地路径），等价于 `local:<path>`，逐步迁移到 `VAULT_SOURCES`。
  - **列表字段写法**：`VAULT_SOURCES` / `INGEST_EXTS` / `INGEST_EXCLUDE_DIRS` 是 `List[str]`。pydantic-settings 默认按 JSON 解析（写 `a,b` 会直接 `SettingsError` 崩溃），因此 `Settings` 用 `Annotated[List[str], NoDecode]` + `_parse_list_field` 校验器放宽为**逗号分隔或 JSON 数组两种写法都支持**，空值返回 `[]`。
- **vault 前端管理（§17.2）**：**`vaults` 表是唯一运行时真相源**；`VAULT_SOURCES` 只是**一次性 bootstrap 种子**——仅在 `vaults` 表为空时注入一次（`origin="env"`，归 `user_id="default"`），之后以 DB 为准，用户在前端删除的 vault 不会被复活。日常使用请在前端「Vault 管理」页增删（本地目录 / 上传 `.zip`），检索/问答按所选 `vault_id` 过滤。无头模式（`UI_ENABLED=false`）例外，每次启动按 `.env` 对账。
- **多用户（§17.3）**：`ENABLE_MULTIUSER=false`（默认）时单用户，所有资源归 `user_id="default"`，接口用 `X-API-Key` 鉴权；`=true` 时启用 `users` 表 + JWT，`POST /api/v1/auth/login` 签发令牌，受保护接口同时接受 `X-API-Key` 与 `Authorization: Bearer <JWT>`。
- **多模型（§18）**：`model_profiles` 表是唯一运行时真相源，`.env` 只提供一次性种子（表空时注入 llm/embed 各一个 `default`）。使用时：LLM 每次请求可选（`llm_profile`），Embedding 在**索引时**选定并绑定 vault，换模型 = 重建索引。**出参永不返回明文密钥**（只给 `api_key_masked`）。
- **`HOST` / `PORT`**：本地运行默认 `127.0.0.1:8000`；**Docker / 服务端部署设为 `0.0.0.0` 以接受容器外访问**（详见 §15）。
- `security`：API Key 用常量时间比对（`hmac.compare_digest`）。v0.1 为单密钥；多用户可平滑升级为 JWT / OAuth（API Key 仍可作为服务间调用保留）。**部署到公网时，API Key 是唯一的访问闸门，必须强随机且通过反向代理 + HTTPS 暴露**（见 §15.4）。
- `CORS`：仅放信任前端 origins，本地开发可用 `*`；**远程访问时收紧为具体前端域名**。
- **不提交 `.env`**（已被 `.gitignore` 忽略）。

## 9. 开发里程碑（建议顺序，逐步可跑）

- **Phase 0 脚手架**：`main.py` + `config` + `database` + `healthz` 能起服务、能看 `/docs`。
- **Phase 1 摄取**：`chunker` + `embedder` + `vectorstore` + `ingest_service` + `/ingest`。
- **Phase 2 检索**：`retrieval_service` + `/search`。
- **Phase 3 问答**：`llm_client` + `chat_service` + `/chat`（SSE）+ 鉴权中间件。
- **Phase 4 持久化与测试**：`conversation_repo` + `note_repo` + `tests/` + 结构化日志。

> 每个 Phase 结束都应能 `curl` 跑通对应接口，再进下一阶段。

## 10. 手写 TODO 地图（按文件，建议实现的类 / 函数签名）

```python
# app/main.py
app = FastAPI(title="notes-rag")
# - 生命周期：启动时建表 / 加载 Chroma；关闭时释放
# - include_router(ingest/search/chat/health)
# - add_middleware(CORSMiddleware)
# - 异常处理器（401 / 500）

# app/core/config.py
class Settings(BaseSettings):
    llm_base_url, llm_api_key, llm_model: str             # LLM 对话 / 问答
    embed_base_url, embed_api_key, embed_model: str       # Embedding（embed_base_url/api_key 留空回退 LLM）
    model_profiles: list[dict]      # 多模型种子 JSON（表为空时注入一次，见 §18.4）
    def bootstrap_profiles(self) -> list[dict]: ...   # .env → 种子配置（llm/embed 各一 default + MODEL_PROFILES 项）
    vault_sources: list[str]        # vault 来源：local:/path, git:..., http(s):...（见 §15.3）
    chroma_dir, sqlite_path: Path
    host, port: str/int             # 本地 127.0.0.1；部署 0.0.0.0
    api_key, cors_origins: str
    host, port: str/int
    model_config = SettingsConfigDict(env_file=".env")

# app/core/security.py
def verify_api_key(raw: str | None, expected: str) -> bool: ...
# 进阶：decode_jwt(token) -> payload

# app/core/database.py
engine = create_async_engine("sqlite+aiosqlite:///...")
async def get_session() -> AsyncSession: ...
async def init_db() -> None: ...   # create_all

# app/models/schemas.py
class IngestRequest(BaseModel): vault_path: str | None = None; vault_sources: list[str] | None = None; vault_id: str | None = None; rebuild: bool = False
class IngestResponse(BaseModel): scanned: int; indexed_chunks: int; elapsed_ms: int
class SearchRequest(BaseModel): query: str; top_k: int = 5; threshold: float = 0.0
class ChunkHit(BaseModel): note_id: str; file_path: str; title: str; content: str; score: float
class SearchResponse(BaseModel): hits: list[ChunkHit]
class ChatRequest(BaseModel): query: str; conversation_id: str | None = None; top_k: int = 5

# app/models/orm.py
class User(Model): ...      # users（多用户，§17.3）
class Vault(Model): ...     # vaults（前端管理，§17.2/§17.4）
class Note(Model): ...      # notes（+ user_id, vault_id 隔离列）
class Chunk(Model): ...     # chunks（+ user_id, vault_id 隔离列）
class Conversation(Model): ...  # conversations（+ user_id, vault_id）
class Message(Model): ...   # messages（+ user_id）

# app/rag/chunker.py
def split_markdown(text: str, max_chars: int = 800) -> list[str]: ...

# app/rag/embedder.py
async def embed(texts: list[str], runtime: ModelRuntime) -> list[list[float]]: ...   # runtime 决定用哪个 embedding 模型

# app/rag/vectorstore.py
class VectorStore:
    def __init__(self, persist_dir: str, collection_name: str = "notes"): ...   # collection 按 (vault, embed 模型) 隔离
    async def add(self, ids, vectors, docs, metadatas): ...
    async def query(self, vector, top_k, threshold) -> list[dict]: ...
    async def reset(self): ...

# app/rag/llm_client.py
async def stream_chat(messages: list[dict], runtime: ModelRuntime) -> AsyncIterator[str]: ...  # stream=True

# app/repositories/note_repo.py
async def upsert_note(session, file_path, title, mtime, chunks) -> None: ...
async def get_note_by_path(session, file_path) -> Note | None: ...

# app/repositories/conversation_repo.py
async def new_conversation(session) -> Conversation: ...
async def append_message(session, conv_id, role, content) -> None: ...

# app/services/ingest_service.py
async def scan(vault_sources: list[str], rebuild: bool = False,
               filters: "IngestFilters | None" = None,
               embed_runtime: "ModelRuntime | None" = None) -> IngestResponse: ...  # 编排 FR1（多源+过滤+多格式+多模型，见 §15.3 / §16 / §18）

# app/parsers/base.py
class ParsedDocument:            # 解析结果：content(str) / title / mtime / meta(dict)
    ...
class DocumentParser(ABC):       # 解析器基类
    supported_exts: tuple[str, ...]
    def parse(self, path: Path) -> ParsedDocument: ...   # 返回纯文本 + 元数据

# app/parsers/registry.py
def register(parser: DocumentParser) -> None: ...
def get_parser(ext: str) -> DocumentParser | None: ...   # 按扩展名取 parser

# app/parsers/markdown.py / text.py        # 一期实现（md / txt）
# app/parsers/pdf.py / docx.py / excel.py  # 预留（依赖可选，见 §16.1）

# app/services/retrieval_service.py
async def retrieve(query: str, top_k: int, threshold: float) -> list[ChunkHit]: ...  # FR2

# app/services/chat_service.py
async def stream(query: str, conversation_id, top_k) -> AsyncIterator[dict]: ...  # FR3

# app/services/vault_service.py   ← 新增：vault 管理编排（§17.2）
async def resolve_local_path(vault: Vault) -> Path: ...        # local→path；uploaded→UPLOAD_DIR/<id>；git/remote→缓存目录
async def save_upload(vault_id: str, file) -> Path: ...         # 接收 zip → 解压到 UPLOAD_DIR/<vault_id>
async def reindex(vault: Vault, rebuild: bool = False,
                  embed_profile: "ModelProfile | None" = None) -> IngestResponse: ...  # 换 embedding 即重建索引（§18.2）

# app/services/model_service.py   ← 新增：多模型解析与选择（§18）
async def resolve_profile(session, settings, kind, ref=None, user_id="default") -> ModelProfile: ...  # 请求→默认→兜底
def to_runtime(profile: ModelProfile, settings: Settings) -> ModelRuntime: ...      # 应用 base_url/api_key 回退
def runtime_from_settings(settings: Settings, kind: str) -> ModelRuntime: ...        # 表为空时的兜底
def build_client(runtime: ModelRuntime) -> AsyncOpenAI: ...
def assert_embed_compatible(vault: Vault, profile: ModelProfile) -> None: ...        # 未建过索引 → EmbedModelMismatch
def collection_name(vault_id, profile_id) -> str: ...    # v{vault}_m{profile}
async def seed_from_env(session, settings) -> list[ModelProfile]: ...                # 表空时注入（§18.4）
async def test_connection(runtime: ModelRuntime) -> ModelTestResult: ...

# app/repositories/model_repo.py   ← 新增（§18.1）
async def create_profile(session, user_id, kind, name, model, base_url="", api_key="", params_json="{}", is_default=False) -> ModelProfile: ...
async def find_by_name(session, user_id, kind, name) -> ModelProfile | None: ...
async def get_default(session, user_id, kind) -> ModelProfile | None: ...
async def set_default(session, profile) -> None: ...    # 同 (user_id, kind) 内其余置 False
async def count_profiles(session, kind=None) -> int: ...

# app/services/ingest_service.py
async def index_vault(vault: Vault, rebuild: bool = False,
                      filters: "IngestFilters | None" = None) -> IngestResponse: ...  # 由 vault 解析本地路径后复用 scan 逻辑（§17.2）

# app/repositories/vault_repo.py   ← 新增
async def create_vault(session, user_id, name, source_type, source_value, filters) -> Vault: ...
async def list_vaults(session, user_id) -> list[Vault]: ...
async def delete_vault(session, vault_id, user_id) -> None: ...   # 同时清该 vault 的 notes/chunks 与向量
async def create_user(session, username, password_hash, is_admin=False) -> User: ...
async def get_user_by_username(session, username) -> User | None: ...

# app/core/security.py
def verify_api_key(raw, expected) -> bool: ...
def hash_password(plain) -> str: ...          # 多用户：bcrypt/scrypt
def verify_password(plain, hashed) -> bool: ...
def create_access_token(user_id: str) -> str: ...   # JWT（多用户）
def get_current_user(...) -> User: ...        # 先判 X-API-Key，再判 Bearer JWT；返回 owner 或登录用户

# app/api/routes/vaults.py   ← 新增：GET/POST/DELETE /api/v1/vaults + reindex
# app/api/routes/auth.py     ← 新增：register / login / me（多用户模式）

# app/mcp/server.py   ← 新增：把上面的 services 封装为 MCP tools（复用，不重写 RAG）
# 传输：stdio（默认）或 FastAPI 挂载 /mcp 端点（Streamable HTTP）
# 工具示例（函数签名，逻辑留手写，见 §14）：
async def mcp_search_notes(query: str, top_k: int = 5, vault_id: str | None = None) -> list[dict]: ...
async def mcp_ask_notes(question: str, vault_id: str | None = None, conversation_id: str | None = None) -> AsyncIterator[str]: ...
async def mcp_ingest_vault(vault_path: str | None = None, reindex: bool = False) -> dict: ...
async def mcp_list_vaults() -> list[dict]: ...
```

## 11. 测试策略

- **单测**：mock `embedder`（返回固定向量）、mock `llm_client`（返回固定流），验证 service 编排与 Prompt 组装正确。
- **集成**：起 `TestClient`，用小样本 vault 跑 `/ingest` → `/search` → `/chat` 全链路。
- **安全**：无 Key 访问受保护接口返回 `401`；错误 Key 返回 `401`。

## 12. 风险与注意

- embedding 维度要与向量库一致；换模型必须重建索引（先 `vectorstore.reset()`）。
- LLM 流式中断要优雅收尾，并保存已生成消息（避免对话历史残缺）。
- 大 vault 的内存 / 耗时：MVP 限制扫描文件数，分批 embedding。
- Chroma 版本兼容：在 `uv.lock` 锁定（pyproject.toml 用 `^` 约束主版本），避免 chromadb 大版本破坏性更新；Intel Mac 需在 `[tool.uv] required-environments` 锁定平台，避开 onnxruntime 无 x86_64 wheel 的坑。
- 不要把 `.env` / `data/` 提交到版本库。

## 13. 开源与可扩展性约定

- 项目以 MIT 协议开源，**不限制使用场景**：个人、团队、商业自托管均可。
- 分层架构（api / services / repositories / rag）保证任一环节可替换、可扩展：
  - **向量库**：Chroma → pgvector / Qdrant / Milvus（实现 `VectorStore` 抽象即可）
  - **LLM / Embed**：OpenAI 兼容 → 任意兼容端点（仅改 `base_url` / `api_key`）
  - **关系库**：SQLite → Postgres（改 engine URL 与 driver 即可，ORM 不变）
- **多租户 / 多 vault**：通过数据模型预留的 `user_id` / `vault_id` 列 + 鉴权中间件透传实现（见 §6）。
- 欢迎社区贡献：新检索策略（reranker / 混合检索）、新向量后端、前端、部署模板（Docker / compose / Helm）等。
- **部署模板已内置**：`deploy/` 目录提供 Dockerfile / docker-compose.yml / nginx 示例，本地运行与服务端部署共用同一套代码与配置（见 §15）。
- 提交规范、PR 流程见仓库根 `CONTRIBUTING.md`。

## 14. Agent 接入方案（MCP / Skill）

> 目标：让项目被 agent（WorkBuddy、OpenClaw 等）当作「个人知识库工具」调用——agent 在对话中自动决定何时检索 / 问答你的笔记。本节给出**方案与骨架**，MCP server 的 `app/mcp/server.py` 已留签名，逻辑由你手写。

### 14.1 两种接入方式对比

| 维度 | MCP server（主线） | Skill（SKILL.md，轻量补充） |
|------|-------------------|------------------------------|
| 形式 | 标准协议，agent 通过 `mcp.json` 配置 | 文本指令文件（AgentSkills 规范，即 SKILL.md） |
| 结构化 | 高：工具带 JSON schema、参数校验、类型 | 低：自然语言描述「如何调 REST / curl」 |
| 是否需改本项目 | 需要（新增 `app/mcp/`） | 不需要（纯外部文档，可放仓库 `skill/`） |
| agent 何时调用 | 按 tool 描述自动决定（结构化） | 按 skill 描述匹配决定（语义） |
| 流式 | 原生支持 | 取决于 skill 怎么写（可 curl SSE） |
| WorkBuddy | ✅ `~/.workbuddy/mcp.json` | ✅ skill 目录 / 市场 |
| OpenClaw | ✅ `~/.openclaw/mcp.json`（其本身是 MCP client + server） | ✅ ClawHub / workspace skill（AgentSkills 规范） |
| 个人用户友好度 | stdio 零端口最省事 | 任意 agent 都能读，零部署 |

**结论**：MCP 是主线（结构化、两 agent 原生支持、工具自动发现）；Skill 是零部署补充（任何支持 system-prompt / skill 的 agent 都能用，不依赖 MCP 实现）。**两者不冲突，可同时提供。**

### 14.2 MCP server 架构（复用 service 层，不重写 RAG）

```
Agent (WorkBuddy / OpenClaw)
   │  MCP：stdio（本地子进程）或 Streamable HTTP（http://127.0.0.1:8000/mcp）
   ▼
app/mcp/server.py          ← 新增层：把 services 封装成 MCP tools
   │  进程内调用，复用同一套逻辑
   ▼
app/services/*             ← 已有：ingest / retrieval / chat 编排
   └─ repositories/ · rag/ · core/ · models/
```

关键点：**MCP tools 直接 import 并调用 `ingest_service` / `retrieval_service` / `chat_service`，不要重写 RAG 逻辑**，避免与 REST 路径逻辑漂移。

### 14.3 暴露的 MCP 工具（建议）

| MCP tool | 对应 service | 说明 |
|----------|--------------|------|
| `search_notes(query, top_k?, vault_id?)` | `retrieval_service.retrieve` | 纯语义检索，返回命中片段 + 出处 |
| `ask_notes(question, vault_id?, conversation_id?)` | `chat_service.stream` | 检索增强问答，流式返回答案 + 引用 |
| `ingest_vault(vault_path?, reindex?)` | `ingest_service.scan` | 触发索引 / 重建 |
| `list_vaults()` | config / note_repo | 列出已配置 / 已索引的 vault |

> 多 vault / 多用户：工具参数透传 `vault_id` / `user_id`，由 §6 隔离列 + §8 鉴权中间件过滤（个人单用户可忽略）。

### 14.4 两种传输模式与个人用户取舍

- **stdio（推荐个人用户）**：agent 在 `mcp.json` 配 `command`，由 agent 拉起子进程，随 agent 生命周期启停，**零端口、零运维**。适合「本机常驻的 agent 随用随查」。
  - 缺点：每个 agent 进程各起一份 service + 向量库实例；需 agent 支持 stdio MCP（WorkBuddy / OpenClaw 均支持）。
- **Streamable HTTP（多 agent 共享 / 流式稳定 / 远程访问）**：在 FastAPI 挂载 `/mcp` 端点（或独立 `uvicorn app.mcp_http:app`），单进程常驻，**多 agent 共享、流式更稳**，也适合「服务端部署后远程 agent 接入」。
  - 监听地址由 `HOST` 决定：本地模式保持 `127.0.0.1`；**服务端部署设为 `0.0.0.0` 时，务必置于反向代理 + API Key 之后、用 HTTPS 暴露**（见 §15.4）。MCP 端点同样受 API Key 保护。

> 当前 MCP 标准（2026）：官方 Python SDK 为 `mcp` 包；传输用 **stdio** 或 **Streamable HTTP**（已取代旧 SSE，不要新建设计为 SSE）。FastMCP 可 ~15 行写完一个 server。

### 14.5 配置示例

**WorkBuddy**（`~/.workbuddy/mcp.json`）：
```json
{
  "mcpServers": {
    "notes-rag": {
      "command": "uv",
      "args": ["--directory", "/abs/path/to/notes-rag", "run", "python", "-m", "app.mcp.server"],
      "env": { "RAG_API_KEY": "你的本地API_KEY", "VAULT_PATH": "/abs/path/to/vault" }
    }
  }
}
```

**OpenClaw**（`~/.openclaw/mcp.json`，格式一致）：
```json
{
  "mcpServers": {
    "notes-rag": {
      "command": "uv",
      "args": ["--directory", "/abs/path/to/notes-rag", "run", "python", "-m", "app.mcp.server"],
      "env": { "RAG_API_KEY": "你的本地API_KEY", "VAULT_PATH": "/abs/path/to/vault" }
    }
  }
}
```

> Streamable HTTP 模式则把 `command/args/env` 换成 `"url": "http://127.0.0.1:8000/mcp"` + `"headers": {"X-API-Key": "..."}`。

### 14.6 轻量补充：Skill（零部署）

仓库可额外提供 `skill/SKILL.md`（或发布到 WorkBuddy skill 目录 / ClawHub），描述「当用户想查自己的笔记时，用 curl 调 `/api/v1/search` 或 `/api/v1/chat`」。这样即使 agent 未配 MCP，也能通过 skill 文本指令调 REST。骨架见仓库 `skill/` 目录（可选，不在 MVP 强制范围）。

### 14.7 运行模式与安全边界（重要）

> 本项目支持**两种运行形态**，逻辑完全一致、仅部署方式与安全边界不同：

- **本地模式（本机常驻 / stdio MCP）**：`HOST=127.0.0.1`，数据全在本地（vault 本地引用、Chroma / SQLite 落本地 `data/`），MCP 用 stdio 零端口最省事。适合「笔记在本机、只给自己用」。
- **服务端部署模式（Docker / 远程访问）**：镜像跑在服务器或本机容器，`HOST=0.0.0.0`，对外提供 REST / MCP（Streamable HTTP）。适合「手机 / 远程 agent / 多端访问」。此模式下：
  - **数据可持久化**：Chroma / SQLite 挂到数据卷（`/app/data`），vault 既可本地引用也可远程导入（§15.3）。
  - **必须 HTTPS + API Key**：禁止裸 `http://0.0.0.0` 直接暴露公网；经反向代理终止 TLS，API Key 作为唯一访问闸门（§15.4）。
  - **CORS 收紧**为具体前端域名。

- **通用安全边界**：
  - 个人单用户：API Key 防本机其他进程偷调；多用户可平滑升级 JWT / OAuth（§8）。
  - **复用不重写**：MCP tools 调 services，逻辑单一来源，便于维护与测试。
  - **启用步骤**：`uv add mcp`（或手动加到 pyproject）→ `uv sync` → 按上表配置 agent 的 `mcp.json`（stdio 用 `command`；远程用 `url` + `headers`）→ 重启 agent。

## 15. 部署方案（本地 / Docker / 远程访问）

> 目标：同一套代码既能本机 `uv run` 跑，也能打包成 Docker 镜像部署到服务器远程访问。
> 部署模板见仓库 `deploy/` 目录（Dockerfile / docker-compose.yml / nginx.conf.example）。

### 15.1 本地运行（开发 / 个人日常）
```bash
uv sync --python 3.12
cp .env.example .env          # 填 LLM_API_KEY / VAULT_SOURCES / API_KEY
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```
浏览器开 `http://127.0.0.1:8000/docs`。默认 `HOST=127.0.0.1`，仅本机可访问。

### 15.2 Docker 部署（服务端 / 远程访问）
```bash
# 构建镜像
docker build -f deploy/Dockerfile -t notes-rag .

# 运行（数据持久化到 ./data，端口映射到宿主 8000）
docker run -d --name notes-rag \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  -e HOST=0.0.0.0 \
  notes-rag
```
或用 `docker-compose`（见 `deploy/docker-compose.yml`）：`docker compose -f deploy/docker-compose.yml up -d --build`。
- **数据持久化**：`/app/data`（Chroma + SQLite）挂卷，容器重建不丢索引。
- **配置**：`.env` 里 `HOST=0.0.0.0`、`VAULT_SOURCES` 指向容器内可访问的本地路径或远程 URL。
- **vault 远程导入**：若 vault 不在服务器本地，用 `git:` / `http(s):` 源（§15.3），服务启动时拉取，无需手动拷贝。

### 15.3 vault 来源：本地引用 vs 远程导入
`VAULT_SOURCES` 支持多源混合，ingest 时逐个拉取索引：

| 前缀 | 含义 | 适用 |
|------|------|------|
| `local:/path` | 本机目录直接引用（零拷贝，推荐本机/挂载卷场景） | 笔记就在运行环境本地 |
| `git:https://.../vault.git` | 克隆远程 git 库到缓存后索引（首次 clone，增量 pull） | 把 GitHub/Gitea 上的 vault 同步进来 |
| `http(s)://.../vault.zip` | 下载压缩包解压后索引 | 一次性/定期分发的 vault |
| `http(s)://.../notes/` | 拉取远程目录（递归）后索引 | 自建笔记服务 |

- v0.1 至少支持 `local` + `git` 两类；`http(s)` 为进阶（见 requirements.md §4）。
- 多 vault 隔离：`vault_id` 由来源顺序 / 名称派生，索引与对话均带 `vault_id`（数据模型已预留，§6）。

### 15.4 远程访问安全（关键）
服务端部署**绝不**裸奔：`http://0.0.0.0:8000` 直曝公网风险极高。
- **必须 API Key**：所有业务接口 Header `X-API-Key`；`.env` 里 `API_KEY` 用强随机（如 `openssl rand -hex 32`）。
- **必须 HTTPS**：在前面放 Nginx / Caddy 终止 TLS（`deploy/nginx.conf.example` 给出反代 + 301 跳转 + 限流模板），应用本身监听 `0.0.0.0` 但只接受内网 / 代理转发。
- **CORS 收紧**：`CORS_ORIGINS` 设为具体前端域名，不用 `*`。
- **MCP 远程**：Streamable HTTP 端点同样走 API Key + HTTPS；本地 stdio 无需暴露端口。
- **不要做**：弱口令、关闭鉴权、把 `.env` 提交进镜像（用 `--env-file` / secret 注入，`.dockerignore` 已忽略 `.env`）。

## 16. 多格式文件与过滤设计（预留）

> 目标：让 ingest 不局限于 Markdown，能扩展到 PDF / Word / Excel / txt 等常见文档；
> 同时提供**文件与文件夹过滤**，避免把 `.git`、构建产物、附件目录等无关文件灌进向量库。
> **一期（v0.1）只实现 `.md` / `.txt`**，其余格式与过滤为「已设计、已预留接口、按需启用」，详见 §4 / requirements.md §4。

### 16.1 文件类型支持矩阵

| 类型 | 扩展名 | 推荐库 | 解析要点 | 一期 |
|------|--------|--------|----------|------|
| Markdown | `.md` | 内置 | 原样文本，标题层级交给 `split_markdown` 保留面包屑 | ✅ 实现 |
| 纯文本 | `.txt` | 内置 | 原样文本，交给 `split_text` 通用切分 | ✅ 实现 |
| PDF | `.pdf` | `pymupdf`(fitz) 或 `pdfplumber` | 按页提取文本；页码可作为 chunk 的 section 来源；扫描版需 OCR（进阶，不在一期） | 🔜 预留 |
| Word | `.docx` | `python-docx` | 段落 + 表格按行转文本；标题样式可近似为面包屑（仅支持 `.docx`，老 `.doc` 不覆盖） | 🔜 预留 |
| Excel | `.xlsx` / `.xls` | `openpyxl`（+ 可选 `pandas`） | 每个 sheet 转成「表名 + 行列文本」的可读字符串 | 🔜 预留 |

- 解析层统一**只输出纯文本**（+ 轻量元数据），与具体的分块 / 嵌入逻辑解耦——换格式只加 parser，不动 RAG 管线。
- 依赖策略：PDF / Word / Excel 的库放进 `[project.optional-dependencies].docs`（见 pyproject.toml），**主线 `uv sync` 不强制安装**；要用某格式时 `uv sync --extra docs`（或单独 `uv add pymupdf`）再补 parser 实现即可。

### 16.2 解析器层抽象（`app/parsers/`）

```
app/parsers/
  base.py      # ParsedDocument + DocumentParser(ABC)
  registry.py  # register() / get_parser(ext)
  markdown.py  # 一期：读 .md 文本
  text.py      # 一期：读 .txt 文本
  pdf.py       # 预留：pymupdf 提取
  docx.py      # 预留：python-docx 提取
  excel.py     # 预留：openpyxl 提取
```

**数据结构与基类契约**（手写参考）：
```python
# app/parsers/base.py
@dataclass
class ParsedDocument:
    content: str                 # 纯文本（已是待分块的原始文本）
    title: str                   # 标题：文件名 或 文档内标题
    mtime: float                 # 修改时间，用于增量
    meta: dict = field(default_factory=dict)  # 可选：页数 / sheet 名 / 来源类型等

class DocumentParser(ABC):
    supported_exts: tuple[str, ...]          # 小写扩展名，如 (".md",)
    @abstractmethod
    def parse(self, path: Path) -> ParsedDocument: ...

# app/parsers/registry.py
_PARSERS: dict[str, DocumentParser] = {}
def register(parser: DocumentParser) -> None: ...        # 模块 import 时自注册
def get_parser(ext: str) -> DocumentParser | None: ...   # 按 ".pdf" / "pdf" 取 parser
```

- `ingest_service.scan` 遍历命中文件后：**先取扩展名 → `get_parser(ext)` → 调 `parse()` 拿纯文本 → 交给 chunker**（`.md` 走 `split_markdown`，其余走 `split_text`）。
- 未知扩展名或 parser 缺失 → 跳过并记日志（不中断整体 ingest）。

### 16.3 过滤设计（文件 / 文件夹）

过滤在「遍历阶段」逐文件判定，顺序如下（前面命中即短路）：

1. **目录排除 `exclude_dirs`**：进入子目录前先判，命中的整目录不递归。默认 `ingest_exclude_dirs`（见 §16.4）。
   - 典型默认：`["node_modules", ".git", ".obsidian", ".trash", "__pycache__", ".venv"]`。
   - 注意：Obsidian vault 的 `.obsidian` 配置目录应排除，但笔记本体在 vault 根下不受影响。
2. **扩展名白名单 `exts`**：仅索引白名单内的扩展名；默认 `["md", "txt"]`（一期），后续追加 `pdf/docx/xlsx/xls`。
3. **`exclude` glob（黑名单路径）**：相对 vault 根的路径模式（如 `templates/**`、`drafts/*`），命中即跳过；优先级高于 `include`。
4. **`include` glob（白名单路径）**：非空时**仅**索引命中的文件；为空表示不限（即全量白名单内文件）。
5. **`max_file_size`（可选）**：超过字节上限的文件跳过并记录警告，防超大文件拖垮内存。

- 过滤与 **mtime 增量**（FR1 已支持）正交：先过滤出候选文件集，再按 mtime 决定增量跳过。
- 全部规则都可由「配置默认值 + 单次请求覆盖」两层提供（见 §16.4）。

### 16.4 配置与 API 预留

**配置（app/core/config.py）**——提供全局默认，请求可覆盖：
```python
# 一期生效：仅 md / txt；其余扩展名随 parser 实现启用
ingest_exts: List[str] = ["md", "txt"]
# 默认排除目录（避免无关目录灌库）
ingest_exclude_dirs: List[str] = [
    "node_modules", ".git", ".obsidian", ".trash", "__pycache__", ".venv",
]
```

**请求体（app/models/schemas.py）**——单次 ingest 可覆盖：
```python
class IngestFilters(BaseModel):
    include: List[str] | None = None      # 相对 vault 的 glob 白名单；空=不限
    exclude: List[str] | None = None      # 相对 vault 的 glob 黑名单；优先于 include
    exts: List[str] | None = None         # 覆盖 ingest_exts
    max_file_size: int | None = None      # 字节上限；None=不限

class IngestRequest(BaseModel):
    vault_path: str                       # 兼容单 vault（等价于 local:<path>）
    vault_sources: List[str] | None = None  # 或直接传多源（覆盖 config）
    rebuild: bool = False
    filters: IngestFilters | None = None  # ← 新增；一期留空走配置默认
```

**服务编排（app/services/ingest_service.py）**：
```python
async def scan(vault_sources: list[str], rebuild: bool = False,
               filters: "IngestFilters | None" = None,
               embed_runtime: "ModelRuntime | None" = None) -> IngestResponse: ...
# 内部：遍历 → 应用 §16.3 过滤 → get_parser(ext) → parse → chunker → embed(embed_runtime) → 入库
#       → 写 chunks.embed_profile_id，collection = v{vault_id}_m{profile_id}（§18.2）
```

### 16.5 启用路径（从一期到全格式）

- **一期**：`ingest_exts=["md","txt"]`，`app/parsers/{markdown,text}.py` 实现；`scan` 已能按 `exts` / `exclude_dirs` 过滤；`IngestFilters` 字段可用（即使前端暂不传）。
- **后续启用 PDF / Word / Excel**：
  1. `uv add pymupdf python-docx openpyxl`（或 `uv sync --extra docs`）；
  2. 在 `app/parsers/{pdf,docx,excel}.py` 补全 `parse()` 实现并自注册；
  3. 把对应扩展名加入 `ingest_exts` 或请求 `filters.exts`。
  - 无需改 chunker / embedder / vectorstore / 检索 / 问答任何代码——解析层已隔离变化。

## 17. 前端页面 / Vault 前端管理 / 多用户可配置（新增）

> 目标：项目从「纯 API」升级为**带 Web UI 的完整 RAG 应用**。
> - 用户通过**前端页面**配置 vault（添加本地目录 / 上传本地 vault 压缩包），不再只在 `.env` 写 `VAULT_SOURCES`；
> - 是否支持**多用户**由配置开关决定，默认关闭（个人单用户），开启后走账号密码 + JWT。
> 本节给出**方案与骨架**，逻辑由你手写。

### 17.1 前端：Vue 3 + Vite SPA

- **技术选型**：Vue 3（`<script setup>`）+ Vite。无 SSR，纯客户端 SPA，构建产物由 FastAPI 直接托管（同一镜像、同一进程，部署最简单）。
- **目录**：仓库根 `frontend/`（源码）独立存在；`npm run build` 产物落到 `app/static/`（被 `.gitignore` 忽略，属构建产物）。
- **路由布局**（前端 `vue-router` 或简单组件切换）：
  - `/` 或 `/vaults`：**Vault 管理** —— 列表 + 「添加本地目录」（填路径）/「上传 vault」（选 `.zip` 上传）+ 每个 vault 的「重建索引」按钮。
  - `/search`：**检索** —— 输入 query，展示命中片段与出处（调 `/api/v1/search`）。
  - `/chat`：**问答** —— 输入框 + SSE 流式回答 + 来源引用（调 `/api/v1/chat`）。
  - `/login`（仅多用户模式）：账号密码登录，拿 JWT 存 localStorage。
- **API 客户端**：`src/api.js` 用 `fetch`/`axios`，`baseURL = /api/v1`；请求头带 `X-API-Key`（单用户）或 `Authorization: Bearer <JWT>`（多用户）。
- **后端托管**：`app/main.py` 在注册 `/api/v1/*` 与 `/docs` 之后，再 `app.mount("/", StaticFiles(directory="app/static", html=True))`。SPA 子路由（如 `/vaults`）靠 `history` 回退到 `index.html`（Vite `build` 产出 SPA，FastAPI 用 `HTMLResponse` 兜底或 `StaticFiles(html=True)` 已处理静态资源；未知路径回退交给前端路由）。
- **开发联调**：`cd frontend && npm install && npm run dev`，Vite 代理 `/api` → `http://127.0.0.1:8000`（见 `frontend/vite.config.js`），后端仍 `uvicorn app.main:app`。

### 17.2 Vault 管理：从配置迁移到「前端可配置实体」

- **vault 成为 DB 实体**（`vaults` 表，见 §17.4），不再只是 `.env` 里的字符串。前端 CRUD 即写库。
- **两种主要来源（前端配置）**：
  | 来源类型 `source_type` | 前端怎么配 | 服务端落点 |
  |------|------|------|
  | `local`（本地目录） | 用户在输入框填**绝对路径** | `source_value = /abs/path`；服务端须能访问该路径（本机部署 / 挂载卷场景最常用） |
  | `uploaded`（上传 vault） | 用户选 `.zip` 上传 | 服务端解压到 `UPLOAD_DIR/<vault_id>/`，`source_value` = 该目录；**任意部署形态都能用**（远程服务器也行） |
  | `git` / `remote`（兼容） | 用户粘贴 git URL 或远程 URL（进阶） | 同 `VAULT_SOURCES` 的 `git:`/`http(s):` 语义；首次 clone/pull 到缓存目录 |
- **与 `.env` 的关系**：`VAULT_SOURCES` 是**一次性 bootstrap 种子**，不是权威配置。

  | 场景 | 行为 |
  |---|---|
  | 首次启动、`vaults` 表为空 | 注入 `.env` 里的每个源，`origin="env"`，归 `user_id="default"` |
  | 表非空（无论前端建过还是曾被注入过） | **不再注入**；以 DB 为准 |
  | 用户在前台删掉某个 `origin="env"` 的 vault | 真删除，**重启不复活** |
  | 无头模式 `UI_ENABLED=false` | 无 UI 可改，每次启动按 `source_value` 对账（查重后 upsert），保证改 `.env` 后重启生效 |
  | 多用户 `ENABLE_MULTIUSER=true` | 种子归 `user_id="default"`；其他用户在前端各自配置自己的 vault |

  实现入口：`vault_service.seed_from_env(session, settings)`（启动时调用一次），
  依赖 `vault_repo.count_vaults()` 判空、`find_by_source()` 对账；`vaults.origin` 列标记来源。
  > 这样收口的原因：避免「`.env` 与 DB 两个真相源打架」——改了 `.env` 不生效、删了又复活，
  > 是多套配置源最常见的线上困惑。
- **reindex 触发**：前端点「重建索引」→ `POST /api/v1/vaults/{id}/reindex` → `vault_service` 解析出本地路径 → 调 `ingest_service.index_vault(vault, rebuild=True)`（复用 §4.1 管线，仅入口从「字符串列表」改为「vault 对象」）。

### 17.3 多用户：可配置开关（默认关闭）

- **配置 `ENABLE_MULTIUSER: bool = False`**（默认个人单用户）。
- **单用户模式（默认）**：
  - 鉴权用 `X-API-Key`（即 `.env` 的 `API_KEY`），所有 vault / 对话归合成 owner `user_id = "default"`。
  - 前端无登录页；用户在设置里填一次 API Key（存 localStorage）即可。
- **多用户模式（`ENABLE_MULTIUSER=true`）**：
  - `users` 表（§17.4）；`POST /api/v1/auth/register`（可选开放注册，或仅 admin 建号）、`POST /api/v1/auth/login` → 返回 JWT。
  - `JWT_SECRET` 用于签名（多用户模式必填）。
  - 受保护接口**统一**接受两种凭证之一：`X-API-Key`（服务/管理员调用，如 MCP、curl）或 `Authorization: Bearer <JWT>`（前端用户）。`get_current_user` 先判 API Key，再判 JWT。
  - 资源隔离：所有 vault / notes / chunks / conversations / messages 带 `user_id`；查询时按当前用户过滤，跨用户不可见。
- **升级路径平滑**：单用户时数据天然都是 `user_id="default"`，开启多用户后老数据无需迁移即归该 owner。

### 17.4 数据模型扩展

**新增表**：
```sql
users(id PK, username UNIQUE, password_hash, is_admin, created_at)
vaults(id PK, user_id, name, source_type, source_value,
       filters_json, created_at, indexed_at)   -- filters_json：该 vault 的摄取过滤（§16.3）
```

**既有表追加隔离列**（§6 原「已预留」本次落实）：
```sql
notes(id PK, user_id, vault_id, file_path UNIQUE, title, mtime, indexed_at)
chunks(id PK, user_id, vault_id, note_id FK, idx, content, char_start, char_end, vector_id UNIQUE)
conversations(id PK, user_id, vault_id, created_at)
messages(id PK, conversation_id FK, user_id, role, content, created_at)
```
- 检索 / 问答按 `user_id`（多用户）与 `vault_id`（所选 vault）过滤；单用户模式 `user_id` 恒为 `"default"`。

### 17.5 API 扩展（草稿）

```
# —— Vault 管理（前端配置，均需鉴权）——
GET    /api/v1/vaults                 # 列出当前用户的 vault
POST   /api/v1/vaults                 # JSON 建库：{ name, source_type: local|git|remote, source_value }
POST   /api/v1/vaults/upload          # multipart 上传：name + file=.zip（source_type=uploaded）
GET    /api/v1/vaults/{id}            # 详情
DELETE /api/v1/vaults/{id}            # 删除（同时清该 vault 的索引与分块记录）
POST   /api/v1/vaults/{id}/reindex    # 触发重建索引（BackgroundTasks 可选）

# —— 多用户鉴权（ENABLE_MULTIUSER=true 时启用）——
POST   /api/v1/auth/register          # { username, password } → { user_id, username }
POST   /api/v1/auth/login             # { username, password } → { access_token, token_type }
GET    /api/v1/auth/me                # 返回当前用户（调试/前端取身份）

# 既有 /ingest 仍保留：兼容「命令行 / MCP 直接传 vault_sources」；
# 前端走 /vaults + /reindex，不直接调 /ingest。
```

### 17.6 部署：多阶段构建前端（见 §15 / deploy/Dockerfile）

- **多阶段 Dockerfile**：
  - Stage 1（`node:20-alpine`）：`cd frontend && npm ci && npm run build` → 产出 `frontend/dist`。
  - Stage 2（`python:3.12-slim` + uv）：`COPY frontend/dist app/static/`，再装 Python 依赖、起 uvicorn。
  - 单进程同时托管 API 与前端，对外只暴露一个端口；静态资源与 `/api` 同源，免 CORS 跨域。
- **本地开发**：前后端分离跑（Vite dev 代理 `/api`），不构建也能联调；要验证产物托管就 `make frontend-build` 后 `uvicorn`。
- **反向代理**：§15.4 的 nginx 仍适用，只需把根路径与 `/api` 一起反代到容器（同源了，CORS 可更收紧或省略）。

> 前端 SPA 是「调用方」，本质仍消费 `/api/v1`；新增大逻辑都在后端 vault/auth，前端只做配置与展示，便于你专注于后端练手。

## 18. 多模型管理（多个 LLM / 多个 Embedding，使用时可选）

### 18.1 数据模型：`model_profiles` 表

一个模型配置 = 一条记录，**LLM 与 Embedding 是两类（`kind='llm' | 'embed'`），各自独立解析默认项**。

```sql
model_profiles(
  id PK, user_id, kind, name, provider, base_url, api_key, model,
  params_json, is_default, enabled, origin, created_at
)
-- 约束：同一 (user_id, kind, name) 唯一；同一 (user_id, kind) 只有一个 is_default=true
```

| 字段 | 说明 |
|---|---|
| `kind` | `llm`（对话/问答）/ `embed`（向量化） |
| `name` | 用户内唯一可读名（`qwen-max` / `bge-m3-local`），**请求里用它选择模型** |
| `provider` | `openai`（OpenAI 兼容协议，覆盖 Qwen / vLLM / 本地服务）；为将来非兼容协议预留 |
| `base_url` / `api_key` | **允许留空 = 回退 `.env` 的 `LLM_*` / `EMBED_*`**（§18.3） |
| `model` | 模型标识（`gpt-4o-mini` / `text-embedding-3-small` / `bge-m3`） |
| `params_json` | 附加参数：`temperature` / `max_tokens` / `dim` / `timeout` … |
| `is_default` | 该 kind 的默认项；未显式指定模型时使用 |
| `origin` | `ui` = 前端/API 创建；`env` = `.env` 种子注入 |

### 18.2 关键约束：**LLM 可随意换，Embedding 不能**

这是本节最容易踩坑、也最需要在写代码前想清楚的一条：

| | LLM（`kind=llm`） | Embedding（`kind=embed`） |
|---|---|---|
| 与数据的耦合 | 无。只影响生成，**每次请求都能换** | **强耦合**。向量空间由模型决定，不同模型的向量**不可互相检索** |
| 选择时机 | 请求级（`ChatRequest.llm_profile`） | **索引级**（`IngestRequest.embed_profile` / reindex 时指定） |
| 换模型的代价 | 零 | **必须对该 vault 重新索引** |
| 存储隔离 | — | 向量按 `collection_name(vault_id, profile_id)` = `v{vault}_m{profile}` 分集合 |

配套落点：
- `vaults.embed_profile_id`：该 vault **当前**用于检索的 embedding 配置（索引完成时写入）。
- `vaults.embed_indexed_profiles`（JSON 数组）：已建过索引的 profile id —— 建过就能直接切回去检索，**不用重灌**。
- `chunks.embed_profile_id`：每条分块由哪个模型生成，便于溯源与按模型清理。
- `model_service.assert_embed_compatible(vault, profile)`：检索前守卫，profile 没建过索引 → 抛 `EmbedModelMismatch`，提示先 reindex。

> **后果提醒**：如果放任「检索时随便选 embedding」，会出现「能召回但结果全是噪声」的静默错误 —— 这是 RAG 项目最典型的隐蔽 bug，所以接口层**故意不暴露** `SearchRequest.embed_profile`。

### 18.3 解析优先级（三级）

```
1) 请求显式指定    ChatRequest.llm_profile / IngestRequest.embed_profile（name 或 id）
       ↓ 找不到 → 抛 ModelNotFound（不静默回退，避免"以为用了 A 其实用的 B"）
2) 用户默认        model_profiles.is_default=true 且 kind 匹配
       ↓ 没有
3) 系统兜底        .env 的 LLM_* / EMBED_*（runtime_from_settings）
       ↓ 仍没有
                   ModelNotConfigured
```

- `base_url` / `api_key` 留空的 profile，在 `to_runtime()` 阶段回退 `.env` 同 kind 配置 —— 这样「多数服务共用一套端点/密钥」时不必重复填。
- rag 层（`embedder` / `llm_client`）**只接受解析后的 `ModelRuntime`**，不认识 DB、用户、默认项等概念 → 依赖方向仍是 `services → rag`，不会反向。

### 18.4 配置来源：与 vault 同规则（DB 为准，`.env` 为一次性种子）

| 场景 | 行为 |
|---|---|
| 首次启动、表为空 | 注入 `.env` 构造的种子：llm/embed 各一个 `default`（取 `LLM_*` / `EMBED_*`），外加 `MODEL_PROFILES` 里的额外项，`origin='env'` |
| 表非空 | **不再注入**，以库为准；用户删掉的种子不复活 |
| 无头模式 `UI_ENABLED=false` | 无 UI 可改，每次启动按 `name` 对账（查重后 upsert） |
| 多用户开启 | 种子归 `default` 用户，其他用户各自在前端配 |

`MODEL_PROFILES`（JSON 数组）用于容器/无头部署预置多套模型：

```bash
MODEL_PROFILES=[{"kind":"llm","name":"qwen","model":"qwen-plus","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","api_key":"sk-xxx","is_default":true},
                {"kind":"embed","name":"bge-m3","model":"bge-m3","base_url":"http://localhost:9997/v1","api_key":"EMPTY"}]
```

### 18.5 API 扩展

```
# —— 模型配置管理（均需鉴权）——
GET    /api/v1/models?kind=llm|embed     # 列表（出参含 api_key_masked，绝不明文返回密钥）
POST   /api/v1/models                    # 新建 { kind, name, model, provider?, base_url?, api_key?, params?, set_default? }
POST   /api/v1/models/test               # 试连「未保存」的配置
GET    /api/v1/models/{id}
PATCH  /api/v1/models/{id}               # 局部更新
DELETE /api/v1/models/{id}               # 被 vault.embed_profile_id 引用 → 409，提示先换模型重建索引
POST   /api/v1/models/{id}/default       # 设为该 kind 的默认项
POST   /api/v1/models/{id}/test          # 试连已保存的配置（embed 返回维度 / llm 返回首块）

# —— 使用时选择 ——
POST   /api/v1/chat      body: { query, vault_id, llm_profile, top_k, conversation_id }
POST   /api/v1/ingest    body: { ..., embed_profile }              # 用哪个 embedding 建索引
POST   /api/v1/search    body: { query, vault_id, top_k, threshold }  # 故意不暴露 embed_profile（§18.2）
POST   /api/v1/vaults/{id}/reindex?embed_profile=<name|id>         # 换 embedding = 重建索引
```

### 18.6 安全约定

- **出参永不返回 `api_key`**，只给 `api_key_masked`（`sk-ab****yz`）。
- 密钥明文存库（个人自部署、本地 SQLite，与 vault 路径同级别的可信数据）。若要更严格：改为只存密钥名、真值放环境变量，或启用 SQLCipher —— 列为后续可选项，**一期不做**。
- 前端「模型管理」页输入密钥后，仅在编辑态可见，保存后列表只显示掩码。

### 18.7 前端交互

- 「模型管理」页：分 LLM / Embedding 两组卡片列表 → 新建 / 编辑 / 设默认 / 试连 / 删除。
- 「问答」页顶部：**LLM 下拉选择**（默认项预选），切换即时生效于下一次提问。
- 「Vault」页：显示该库当前 embedding；换 embedding 时提示「需重建索引」，并给出 reindex 按钮。
- 删除被引用的 embedding 配置 → 前端提示先换模型重建索引。
