# 开发方案设计 — rag-as-api

> 本文给出架构、分层职责、API 草稿、数据模型、RAG 管线与**手写 TODO 地图**。
> 所有 `.py` 业务逻辑由你手写实现；本仓库只提供目录骨架与本文。
> 配合 [需求清单与范围边界](requirements.md)。

## 1. 架构总览

分层架构，依赖方向自上而下（api → services → repositories / rag → core / models）：

```
Client (curl / 前端 / Obsidian 插件)
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
    deps.py              # 依赖注入：get_config / get_db / get_current_api_key / get_clients
    routes/
      ingest.py          # POST /api/v1/ingest
      search.py          # POST /api/v1/search
      chat.py            # POST /api/v1/chat (SSE 流式)
      health.py          # GET /healthz
  core/
    config.py            # Settings（pydantic-settings）读取 .env
    security.py          # API Key / JWT 校验
    database.py          # SQLite 引擎 / session / 建表
  models/
    schemas.py           # 请求 / 响应 Pydantic 模型
    orm.py               # SQLAlchemy 表：notes / chunks / conversations / messages
  repositories/
    note_repo.py         # 笔记与分块元数据 CRUD
    conversation_repo.py # 对话与消息 CRUD
  services/
    ingest_service.py    # 扫描→解析→分块→embedding→入库 编排
    retrieval_service.py # 查询→embedding→向量检索→组装上下文
    chat_service.py      # retrieval + LLM 流式生成 + 历史
  rag/
    chunker.py           # Markdown 切分策略
    embedder.py          # 文本→向量（OpenAI 兼容 embedding，async）
    vectorstore.py       # Chroma 封装：add / query / reset
    llm_client.py        # LLM 调用（chat.completions.create, stream=True）
  mcp/
    server.py             # 新增：MCP server（stdio / Streamable HTTP），把 services 封装成 tools ← 手写
tests/
  conftest.py, test_ingest.py, test_search.py, test_chat.py, test_security.py
scripts/
  init_db.py             # 建表脚本（也可在 database.py 内 create_all）
```

## 3. 技术选型与理由

| 组件 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | 异步原生、Pydantic 校验、自动 OpenAPI 文档，练手+日常都香。 |
| 配置 | pydantic-settings | 配置与 schema 统一，类型安全读取 `.env`。 |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite | 元数据/历史持久化，练习 ORM + async session。 |
| 向量库 | Chroma（chromadb） | 本地持久化、零部署、API 简单；后期可换 pgvector。 |
| LLM/Embed | openai SDK（兼容） | embedding + chat 共用，base_url 指向 Qwen/兼容端点，换模型只改配置。 |
| 服务器 | Uvicorn | ASGI 服务器。 |
| 重试/日志 | tenacity / rich（可选） | LLM 调用重试、日志美化。 |

## 4. 数据流与时序

### 4.1 Ingest
```
POST /ingest
  → ingest_service.scan(vault_path)
  → 对每个 .md：读文本 → chunker.split → embedder.embed(chunks)
  → vectorstore.add(ids, vectors, metadatas)
  → note_repo.upsert(note, chunks)
  → 返回 { scanned, indexed_chunks, elapsed_ms }
```
MVP 同步返回汇总；进阶用 `BackgroundTasks`（不强制）。

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
  body: { "vault_path": str, "rebuild": bool = false }
  resp: { "scanned": int, "indexed_chunks": int, "elapsed_ms": int }

POST /api/v1/search
  body: { "query": str, "top_k": int = 5, "threshold": float = 0.0 }
  resp: { "hits": [ { "note_id", "file_path", "title", "content", "score" } ] }

POST /api/v1/chat
  body: { "query": str, "conversation_id": str | null, "top_k": int = 5 }
  resp: text/event-stream (SSE)
    data: {"type":"token","text":"..."}
    data: {"type":"sources","items":[{"file_path","title","score"}]}
    data: {"type":"done"}

GET /healthz  → { "status": "ok" }
```
**鉴权**：受保护接口 Header `X-API-Key: <key>`（或 Bearer JWT）。`/healthz` 免鉴权。
**版本前缀**：所有业务接口挂 `/api/v1`。

## 6. 数据模型

**SQLite 表（SQLAlchemy ORM，见 models/orm.py）**
```sql
notes(id PK, file_path UNIQUE, title, mtime, indexed_at)
chunks(id PK, note_id FK, idx, content, char_start, char_end, vector_id UNIQUE)
conversations(id PK, created_at)
messages(id PK, conversation_id FK, role, content, created_at)
```

**向量库（Chroma）collection = "notes"**
- `ids` = chunk 的 `vector_id`
- `embeddings` = embedder 输出
- `metadatas` = `{ note_id, file_path, title, chunk_idx }`

> 注意：embedding 维度必须与向量库一致；换 embedding 模型必须重建索引。

## 7. RAG 管线设计

- **分块（chunker）**：按 Markdown 标题层级 + 长度上限（如 ~800 字 / ~200 token）滑动切分；保留标题面包屑作为上下文前缀，提升检索相关性。
- **嵌入（embedder）**：text-embedding 兼容模型；批量 embedding 控并发与限速。
- **检索（vectorstore）**：余弦相似度 Top-K；`threshold` 过滤低分噪声。
- **Prompt 模板**：system 说明「只依据 `<context>` 回答，笔记里没有就直说不知道」；user = 上下文片段 + 问题。
- **流式（llm_client）**：`stream=True`，逐 token yield；结束时回传 `sources`。
- **防幻觉**：要求引用来源；禁止编造 vault 外知识（写入 system prompt）。

## 8. 配置与安全

- `.env` 字段：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` / `EMBED_MODEL` / `VAULT_PATH` / `CHROMA_DIR` / `SQLITE_PATH` / `API_KEY` / `CORS_ORIGINS` / `HOST` / `PORT`。
- `security`：API Key 用常量时间比对（`hmac.compare_digest`）。v0.1 为单密钥；多用户可平滑升级为 JWT / OAuth（API Key 仍可作为服务间调用保留）。
- `CORS`：仅放信任前端 origins，本地开发可用 `*`。
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
app = FastAPI(title="rag-as-api")
# - 生命周期：启动时建表 / 加载 Chroma；关闭时释放
# - include_router(ingest/search/chat/health)
# - add_middleware(CORSMiddleware)
# - 异常处理器（401 / 500）

# app/core/config.py
class Settings(BaseSettings):
    llm_base_url, llm_api_key, llm_model, embed_model: str
    vault_path, chroma_dir, sqlite_path: Path
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
class IngestRequest(BaseModel): vault_path: str; rebuild: bool = False
class IngestResponse(BaseModel): scanned: int; indexed_chunks: int; elapsed_ms: int
class SearchRequest(BaseModel): query: str; top_k: int = 5; threshold: float = 0.0
class ChunkHit(BaseModel): note_id: str; file_path: str; title: str; content: str; score: float
class SearchResponse(BaseModel): hits: list[ChunkHit]
class ChatRequest(BaseModel): query: str; conversation_id: str | None = None; top_k: int = 5

# app/models/orm.py
class Note(Model): ...      # notes
class Chunk(Model): ...     # chunks
class Conversation(Model): ...  # conversations
class Message(Model): ...   # messages

# app/rag/chunker.py
def split_markdown(text: str, max_chars: int = 800) -> list[str]: ...

# app/rag/embedder.py
async def embed(texts: list[str]) -> list[list[float]]: ...   # OpenAI 兼容 async

# app/rag/vectorstore.py
class VectorStore:
    def __init__(self, persist_dir: str): ...
    async def add(self, ids, vectors, docs, metadatas): ...
    async def query(self, vector, top_k, threshold) -> list[dict]: ...
    async def reset(self): ...

# app/rag/llm_client.py
async def stream_chat(messages: list[dict]) -> AsyncIterator[str]: ...  # stream=True

# app/repositories/note_repo.py
async def upsert_note(session, file_path, title, mtime, chunks) -> None: ...
async def get_note_by_path(session, file_path) -> Note | None: ...

# app/repositories/conversation_repo.py
async def new_conversation(session) -> Conversation: ...
async def append_message(session, conv_id, role, content) -> None: ...

# app/services/ingest_service.py
async def scan(vault_path: str, rebuild: bool) -> IngestResponse: ...  # 编排 FR1

# app/services/retrieval_service.py
async def retrieve(query: str, top_k: int, threshold: float) -> list[ChunkHit]: ...  # FR2

# app/services/chat_service.py
async def stream(query: str, conversation_id, top_k) -> AsyncIterator[dict]: ...  # FR3

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
- **Streamable HTTP（多 agent 共享 / 流式稳定）**：在 FastAPI 挂载 `/mcp` 端点（或独立 `uvicorn app.mcp_http:app`），单进程常驻，**多 agent 共享、流式更稳**。
  - 缺点：需起一个端口、监听 `127.0.0.1`、用 API key 保护；个人本地用足够，不要暴露到 `0.0.0.0`。

> 当前 MCP 标准（2026）：官方 Python SDK 为 `mcp` 包；传输用 **stdio** 或 **Streamable HTTP**（已取代旧 SSE，不要新建设计为 SSE）。FastMCP 可 ~15 行写完一个 server。

### 14.5 配置示例

**WorkBuddy**（`~/.workbuddy/mcp.json`）：
```json
{
  "mcpServers": {
    "rag-as-api": {
      "command": "uv",
      "args": ["--directory", "/abs/path/to/rag-as-api", "run", "python", "-m", "app.mcp.server"],
      "env": { "RAG_API_KEY": "你的本地API_KEY", "VAULT_PATH": "/abs/path/to/vault" }
    }
  }
}
```

**OpenClaw**（`~/.openclaw/mcp.json`，格式一致）：
```json
{
  "mcpServers": {
    "rag-as-api": {
      "command": "uv",
      "args": ["--directory", "/abs/path/to/rag-as-api", "run", "python", "-m", "app.mcp.server"],
      "env": { "RAG_API_KEY": "你的本地API_KEY", "VAULT_PATH": "/abs/path/to/vault" }
    }
  }
}
```

> Streamable HTTP 模式则把 `command/args/env` 换成 `"url": "http://127.0.0.1:8000/mcp"` + `"headers": {"X-API-Key": "..."}`。

### 14.6 轻量补充：Skill（零部署）

仓库可额外提供 `skill/SKILL.md`（或发布到 WorkBuddy skill 目录 / ClawHub），描述「当用户想查自己的笔记时，用 curl 调 `/api/v1/search` 或 `/api/v1/chat`」。这样即使 agent 未配 MCP，也能通过 skill 文本指令调 REST。骨架见仓库 `skill/` 目录（可选，不在 MVP 强制范围）。

### 14.7 个人用户特别注意事项（重要）

- **数据不出本机**：vault 本地、Chroma 本地、SQLite 本地；stdio 是本地进程，http 仅监听 `127.0.0.1`。
- **零外部服务**：不依赖公网、不强制云部署；MVP 用 stdio 即可。
- **配置极简**：`mcp.json` 一行 + `.env` 填 API key。
- **安全边界**：个人单用户，API key 防本机其他进程偷调；**不要做 OAuth / 多租户重活**（§8 已说明可平滑升级）；MCP server 绝不监听 `0.0.0.0`。
- **复用不重写**：MCP tools 调 services，逻辑单一来源，便于维护与测试。
- **启用步骤**：`uv add mcp`（或手动加到 pyproject）→ `uv sync` → 按上表配置 agent 的 `mcp.json` → 重启 agent。
