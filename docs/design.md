# 开发方案设计（大纲）— notes-rag

> **本文档只保留「大纲 + 基础介绍 + 全局约定」。**
> 模块级详细方案（数据模型、摄取管线、检索、问答、Vault/多用户、前端、多模型、MCP、部署、多格式、测试）
> 已拆分为独立设计文档，见 **§11 模块设计文档索引**。
>
> 本项目所有 `.py` 业务逻辑由你手写实现；本仓库只提供目录骨架与设计文档。
> 需求清单与范围边界见设计文档库的 `requirements.md`（路径见 §11）。

---

## 1. 项目简介

`notes-rag` 是一个**自托管的个人知识库 RAG 应用**：把 Obsidian vault / 本地笔记目录 → 解析分块 → 向量化入库 → 语义检索 → 检索增强问答，并可作为工具被 Agent（WorkBuddy / OpenClaw 等）调用。

**定位**：

| 面向 | 说明 |
|---|---|
| 练手 | 分层架构（api / services / repositories / rag）完整，适合练 FastAPI + SQLAlchemy async + RAG 工程 |
| 实用 | 可作为自托管知识库服务直接部署（本地 / Docker / 远程访问） |
| 可扩展 | 向量库、LLM、Embedding、关系库、文件格式均为可替换的扩展点 |

**关键能力一览**：

- 多源 vault 摄取（本地引用 / 上传 zip / git / 远程），支持文件与文件夹过滤
- 多格式解析（一期 `.md` / `.txt`，PDF / Word / Excel 已预留契约）
- **多 LLM / 多 Embedding 可配置可选**（LLM 每次请求可换；Embedding 与索引绑定，换模型需重建索引）
- 前端 SPA（Vault 管理 / 检索 / 问答 / 模型管理），同源托管单端口
- 多用户可配置开关（默认个人单用户）
- Agent 接入（MCP server：stdio / Streamable HTTP）

---

## 2. 架构总览

分层架构，依赖方向自上而下（`api → services → repositories / rag → core / models`）：

```
Client (curl / 前端 SPA / Obsidian 插件 / Agent)
   │  HTTP (JSON / SSE)
   ▼
app/api/          路由层：接收请求、校验、调 service、组装响应，不含业务逻辑
   │
   ▼
app/services/     业务层：编排 ingest / retrieval / chat / vault / model 流程
   ├─────────────► app/repositories/   数据访问：SQLite 读写（笔记元数据、对话、配置）
   └─────────────► app/rag/            RAG 管线：chunker / embedder / vectorstore / llm_client
   │
   ▼
app/core/         横切：config / security / database / middleware
app/models/       Pydantic schemas + ORM 定义
app/parsers/      解析层：按扩展名路由 parser（格式差异隔离在此）
app/mcp/          Agent 接入：把 services 封装为 MCP tools
```

**依赖原则**

- 路由层不写业务逻辑；service 不碰 HTTP；repository 不碰 RAG；rag 不碰 FastAPI。
- **`rag` 层只接受已解析的 `ModelRuntime`**，不认识 DB / 用户 / 默认项（避免依赖反转）。
- 依赖通过 FastAPI `Depends` 注入（config、db session、clients）。
- `core` 可被任何层 import，但 `core` 不得 import 业务层（`database.py` 依赖 `models.orm` 是允许的向下依赖）。

**两类存储的职责**：SQLite 承载结构化元数据（权威）；Chroma 承载向量（**可重建的派生索引**，不一致时以重建索引修复）。

---

## 3. 目录结构与职责（手写地图总览）

```
app/
  main.py                # FastAPI 实例、生命周期（建表 + 清理残留作业 + 定时同步）、挂载路由、CORS、异常处理器、静态托管   ← 手写
  api/
    deps.py              # 依赖注入：get_settings / get_session / get_current_api_key / get_current_user_id / get_vector_store
    routes/
      ingest.py          # POST /api/v1/ingest（提交作业，202）
      search.py          # POST /api/v1/search
      chat.py            # POST /api/v1/chat (SSE 流式)
      health.py          # GET /healthz
      vaults.py          # /api/v1/vaults CRUD + sync / reindex / runs / runs/{rid} / cancel / doctor
      auth.py            # register / login / me（多用户模式）
      models.py          # 多模型 CRUD / 设默认 / 试连
  core/
    config.py            # Settings（pydantic-settings）读取 .env
    security.py          # API Key / JWT 校验
    database.py          # SQLite 异步引擎 / session（含请求外的 session_scope）/ 建表
    middleware.py        # 请求日志中间件
  models/
    schemas.py           # 请求 / 响应 Pydantic 模型（含 Vault / User / Token / ModelRuntime / SyncRunOut）
    orm.py               # SQLAlchemy 表：users / vaults / notes / chunks / conversations / messages / model_profiles / sync_runs
  repositories/
    note_repo.py         # 笔记与分块元数据 CRUD
    conversation_repo.py # 对话与消息 CRUD
    vault_repo.py        # vault / user CRUD
    model_repo.py        # 模型配置 CRUD / 设默认 / 计数
    sync_repo.py         # 作业记录 CRUD / 进度更新 / 取消 / 裁剪 / 启动清理
  services/
    run_service.py       # 作业层：提交/抢锁、进度节流上报、协作式取消、启动清理、定时同步
    sync_service.py      # 对账层：变更判据、四类变更、删除三护栏、dry_run、doctor
    ingest_service.py    # 原语层：单文件 index_file / drop_file / move_file（解析→分块→嵌入→写入）
    retrieval_service.py # 查询 → embedding → 向量检索 → 组装上下文
    chat_service.py      # retrieval + LLM 流式生成 + 历史
    vault_service.py     # vault 解析为本地路径 / 上传解压 / 提交作业（不实现索引逻辑）
    model_service.py     # 多模型解析（三级优先级）/ 构造客户端 / embedding 一致性守卫
    watcher.py           # 文件系统监听（二期）：仅标脏 + debounce 后提交作业
  rag/
    chunker.py           # split_markdown（带面包屑）/ split_text（通用）
    embedder.py          # 文本 → 向量（OpenAI 兼容 embedding，async）
    vectorstore.py       # Chroma 封装：add / query / reset
    llm_client.py        # LLM 调用（chat.completions.create, stream=True）
  parsers/               # 多格式解析层（一期仅 md/txt，其余预留）
    base.py              # DocumentParser 抽象基类 + ParsedDocument（含自注册）
    registry.py          # register / get_parser
    markdown.py · text.py            # 一期实现
    pdf.py · docx.py · excel.py      # 预留（依赖可选，见 pyproject 的 docs extra）
  mcp/
    server.py            # MCP server（stdio / Streamable HTTP），把 services 封装成 tools  ← 手写
  static/                # 构建后的前端静态产物（由 frontend/ 构建产出，gitignore）
tests/
  conftest.py, test_ingest.py, test_search.py, test_chat.py,
  test_security.py, test_vault.py, test_auth.py, fixtures/sample_vault/
scripts/
  init_db.py             # 建表脚本（也可在 database.py 内 create_all）
frontend/                # Vue 3 + Vite SPA 源码，build → app/static
  src/jobs.js            # 作业前端共用常量：阶段中文化 / 状态语义 / 进度形态 / 轮询间隔
  src/components/TasksView.vue     # 任务与进度页（/tasks）
  src/components/JobProgress.vue   # 进度条（三态自适应，卡片 / 任务页共用）
deploy/                  # 部署模板
  Dockerfile             # 多阶段：node 构建前端 → python:3.12-slim + uv
  docker-compose.yml     # 服务 + 数据卷 + 反向代理（可选）
  nginx.conf.example     # 反向代理 + TLS 终止 + 限流 + 关缓冲示例
docs/
  design.md              # ← 本文（大纲 + 基础介绍）
```

---

## 4. 技术选型与理由

| 组件 | 选型 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | 异步原生、Pydantic 校验、自动 OpenAPI 文档 |
| 配置 | pydantic-settings | 配置与 schema 统一，类型安全读取 `.env` |
| ORM | SQLAlchemy 2.0 (async) + aiosqlite | 元数据/历史持久化；练习 ORM + async session |
| 向量库 | Chroma（chromadb） | 本地持久化、零部署、API 简单；后期可换 pgvector / Qdrant |
| LLM（对话） | openai SDK（兼容） | 换模型只改配置；多模型见 M08 |
| Embedding（向量化） | openai SDK（兼容） | 默认回退 LLM 同款端点/密钥，也可独立指向 BGE-M3 / 本地服务 |
| 前端 | Vue 3 + Vite | 无 SSR 的纯 SPA；构建产物由 FastAPI 同源托管 |
| MCP | 官方 `mcp` Python SDK | stdio / Streamable HTTP；~15 行可写完一个 server |
| 服务器 | Uvicorn | ASGI 服务器 |
| 部署 | Docker（python:3.12-slim + uv） | 本地与服务端共用同一镜像；数据卷持久化 |
| 反向代理 | Nginx / Caddy（可选，生产） | 终止 TLS、HTTP→HTTPS、限流，保护 `0.0.0.0` 端口 |
| 重试 / 日志 | tenacity / loguru（可选） | LLM 调用重试、结构化日志 |

> 选型横向对比与依据见设计文档库的 `libs-comparison.md`；RAG 方略详解见 `vector-rag-embedding.md`。

---

## 5. 数据流总览

> 三张流程只给骨架，完整时序、异常与降级见 M03 / M04 / M05。

### 5.1 Ingest（摄取）

**索引一律是异步作业**：接口立即返回 `202 + run_id`，执行在后台协程里推进（见 M03 §5.13）。

```
POST /ingest（或 /vaults/{id}/sync）
  → 归一化源 → 幂等 upsert 出 vault 实体 → 逐个提交作业，返回 { run_ids }（HTTP 请求到此结束）
  ---- 以下在后台作业里执行，前端轮询进度 ----
  → probe  校验源可达（不可达 → ABORT，绝不当成「内容全没了」）
  → scan   遍历 + 过滤（排除目录 → 扩展名白名单 → exclude glob → include glob → 大小上限）
  → diff   与 notes 对账（新增 / 修改 / 移动 / 未变 / 删除 / 移出范围）
  → plan   删除三护栏判定
  → index  每文件：get_parser(ext) → parse() → ParsedDocument（纯文本 + 元数据）
           chunker：.md 用 split_markdown（保留标题面包屑）；其余用 split_text
           embedder.embed(chunks, runtime) → vectorstore.add(...)
           note_repo.upsert_note(...)        （SQLite 权威元数据）
  → prune  清理磁盘上已不存在的文件
  → done   写 sync_runs 终态与计数
```

**为什么不做同步返回**：全量重建 2–10 min（嵌入是瓶颈），同步返回必撞网关 60s 超时；
而 `wait` 参数只是把复杂度从「客户端轮询」搬到「服务端的取消语义」上，并没有消除它
（漏 `shield` 即等于「超时静默取消任务」）。详见 M03 §5.13.1 与 ADR-12。

**写入顺序**：先写 SQLite 再写 Chroma，向量缺失可由 `doctor --repair` / reindex 修复。

### 5.1.1 增量同步（变更管理）

首次灌库与日常维护共用同一条管线，差别是「多一个对账环节」与「写入粒度为文件」：

```
POST /vaults/{id}/sync（或 /ingest?mode=sync）→ 202 { run_id }，随后后台推进：
  → 前置校验：源可达？（不可达 → ABORT，绝不当成「内容全没了」）
  → 遍历 + 过滤 → seen；对账 known（notes.file_path）
  → 分类：新增 / 修改 / 移动 / 未变 / 删除 / 移出范围
      判据：L1 = size_bytes + mtime_ns（遍历 stat 即得，零成本）
            L2 = content_hash（仅 L1 不一致时计算，识别「时间戳变了但内容没变」）
  → dry_run？→ 作业停在 stage=plan_ready，产出 SyncPlan（不写任何存储）
  → 删除三护栏（源可达 / 扫描完整 / 删除比例 ≤ 阈值）→ 未通过则本轮只增不删
  → 执行：每个变动文件「先删旧 chunks + 旧向量，再写新的」（文件级替换）
  → 记 sync_runs（计数 + 失败文件清单 + 终态）

进度：GET /vaults/{id}/runs/{rid}   取消：POST /vaults/{id}/runs/{rid}/cancel（文件边界生效）
```

> 完整方案（判据四象限、移动配对、护栏阈值、`sync_runs` 可观测、`doctor` 三向自检）见 **M03 §5.8–§5.12**；
> 作业化执行与进度可视化（阶段模型、节流上报、协作式取消、三类失败终态）见 **M03 §5.13**。

### 5.2 Search（检索）

```
POST /search
  → retrieval_service.retrieve(query, top_k, threshold, vault_id)
  → 解析该 vault 生效的 embedding（vaults.embed_profile_id）→ 一致性守卫
  → embedder.embed([query]) → vectorstore.query(vector, top_k, threshold)
  → 组装 ChunkHit（note_id / file_path / title / content / score）
```

**接口层故意不暴露 `embed_profile`** —— 检索必须用建索引时那个模型（见 M04 §5.3）。

### 5.3 Chat（SSE 流式）

```
POST /chat  { query, conversation_id?, top_k, vault_id?, llm_profile? }
  → 解析 LLM（三级优先级）→ retrieval_service.retrieve(...)
  → 组装 system（只依据 <context> 回答，禁止编造）+ 上下文片段 + history
  → llm_client.stream_chat(messages, runtime) → 逐 token yield
  → SSE: data:{"type":"token","text":"..."} … {"type":"sources",...} {"type":"done"}
  → 落库 user / assistant 消息（中途断开也保存已生成部分）
```

前端用 `fetch` 读 stream（`EventSource` 无法带鉴权头）。

---

## 6. 接口总览

> 全部业务接口挂 `/api/v1`；`/healthz` 免鉴权。详细契约（入参校验、错误语义）见对应模块文档。

| 方法 | 路径 | 用途 | 详见 |
|---|---|---|---|
| POST | `/api/v1/ingest` | **提交索引作业**（命令行 / MCP 用；多源 = 多作业）→ `202` | M03 §5.7 |
| POST | `/api/v1/search` | 语义检索（`vault_id` 过滤；不含 `embed_profile`） | M04 |
| POST | `/api/v1/chat` | 检索增强问答（SSE 流式；可选 `llm_profile`） | M05 |
| GET | `/healthz` | 健康检查 | — |
| GET / POST | `/api/v1/vaults` | 列出 / 新建 vault（JSON） | M06 |
| POST | `/api/v1/vaults/upload` | 上传 vault（multipart `.zip`） | M06 |
| GET / DELETE | `/api/v1/vaults/{id}` | 详情 / 删除（连带清索引与分块） | M06 |
| POST | `/api/v1/vaults/{id}/sync` | **提交同步作业** → `202 { run_id }`；`dry_run` 可预览计划 | M03 §5.8–§5.10 |
| POST | `/api/v1/vaults/{id}/reindex` | **提交全量重建作业** → `202`（换 embedding 带 `?embed_profile=`） | M06 / M08 |
| GET | `/api/v1/vaults/{id}/runs` | 历史作业列表（含运行中；由前端置顶） | M03 §5.11 |
| GET | `/api/v1/vaults/{id}/runs/{rid}` | 作业详情与**进度轮询**（`stage` / `total` / `processed` / `current_item`） | M03 §5.13 |
| POST | `/api/v1/vaults/{id}/runs/{rid}/cancel` | 请求取消 → `204`（协作式，文件边界生效） | M03 §5.13 |
| GET / POST | `/api/v1/vaults/{id}/doctor` | 三向一致性自检（幽灵向量 / 缺失向量 / 孤儿笔记 / 模型错配） | M03 §5.12 |
| GET / POST | `/api/v1/models` | 列出（密钥仅掩码）/ 新建模型配置 | M08 |
| POST | `/api/v1/models/test` | 试连未保存的配置 | M08 |
| GET / PATCH / DELETE | `/api/v1/models/{id}` | 详情 / 局部更新 / 删除（被引用返回 409） | M08 |
| POST | `/api/v1/models/{id}/default`、`/test` | 设为该 kind 默认 / 试连已保存配置 | M08 |
| POST | `/api/v1/auth/register`、`/login` | 注册 / 登录（`ENABLE_MULTIUSER=true`） | M06 |
| GET | `/api/v1/auth/me` | 当前用户身份 | M06 |

**鉴权**：受保护接口 Header `X-API-Key: <key>` 或 `Authorization: Bearer <JWT>`；后端**先判 API Key，再判 JWT**。

**写入类端点一律立即返回 `202`**，不等作业跑完 —— 全量重建 2–10 min，同步返回必撞网关超时。
客户端拿 `run_id` 后轮询 `runs/{rid}`（M03 §5.13.1 / ADR-12）。

**同一 vault 已有作业在跑 → `409` + `existing_run_id`（不排队）**，前端据此跳到那个任务的进度视图，
而不是收到一个静默失效的请求（M06 ADR-8）。**取消用 `POST` 而非 `DELETE`**：取消只是请求停止执行，
记录必须保留（它是排查依据与历史），`DELETE /runs/{rid}` 会被读成「删除记录」。

**为什么「建库」与「上传」是两个端点**：FastAPI 同一端点不能同时接收 Pydantic JSON body 与 `UploadFile`（请求体只能解析一次）。

---

## 7. 数据模型总览

> 字段级设计、索引约束、隔离策略与一致性策略见 **M02 数据模型与持久化**。

**SQLite 表（SQLAlchemy ORM，见 `models/orm.py`）**

```sql
users(id PK, username UNIQUE, password_hash, is_admin, created_at)
vaults(id PK, user_id, name, source_type, source_value,
       embed_profile_id, embed_indexed_profiles, filters_json,
       origin, created_at, indexed_at)
notes(id PK, user_id, vault_id, file_path, title,
      size_bytes, mtime_ns, content_hash, indexed_at, last_seen_at)
       -- UNIQUE(vault_id, file_path)；file_path 为相对 vault 根的相对路径
chunks(id PK, user_id, vault_id, note_id FK, idx, content,
       char_start, char_end, vector_id UNIQUE, embed_profile_id)
conversations(id PK, user_id, vault_id, created_at)
messages(id PK, conversation_id FK, user_id, role, content, created_at)
model_profiles(id PK, user_id, kind, name, provider, base_url, api_key, model,
               params_json, is_default, enabled, origin, created_at)
sync_runs(id PK, user_id, vault_id, trigger, mode, dry_run,
          status,  -- queued|running|success|partial|failed|cancelled|aborted
          stage, total, processed, current_item, message, cancel_requested,
          adds, updates, moves, deletes, unchanged, failed_cnt,
          embed_profile_id, blocked_reason, error, detail_json,
          started_at, finished_at, elapsed_ms)
```

- **隔离列**：`notes` / `chunks` / `conversations` / `messages` 均带 `user_id` + `vault_id`；单用户模式 `user_id` 恒为 `"default"`。
- **关键语义**：`vaults.embed_profile_id` = 当前检索用的 embedding；`vaults.embed_indexed_profiles` = 已建过索引的模型（建过即可直接切回，不用重灌）。
- **变更判据字段**：`notes.size_bytes` + `notes.mtime_ns` 为快判据，`notes.content_hash` 为权威判据（见 §5.1.1）。
- **同步留痕**：`sync_runs` 记录每次同步 / 重建的计数、护栏拦截原因与失败文件清单（方案见 M03 §5.11）。
- **作业载体**：`sync_runs` 同时是异步任务的持久化载体 —— `status` 七态、`stage` / `total` / `processed` / `current_item` 为进度列，
  其中 `total IS NULL` 表示**该阶段总量不可知**（`scan`），前端进度条据此转「不确定态」（M03 §5.13.3）。
  之所以「可观测记录」与「任务状态」共用一张表：二者一对一、同生命周期，拆表只会多一次 join（M03 ADR-13）。

**向量库（Chroma）**

- `collection` 命名 `v{vault_id}_m{profile_id}`，按 (vault, embedding 模型) **物理隔离**。
- `ids` = `chunks.vector_id`；`documents` = 分块原文；`metadatas` = `{ note_id, file_path, title, chunk_idx }`。
- **维度一致性**：改变维度 = 换模型 = 换 collection + 重建索引。

---

## 8. 配置总览

> 字段级语义、列表字段解析坑、派生方法见 **M01 基础框架与配置**；部署形态相关见 **M10 部署方案**。

**LLM 与 Embedding 分开配置**：

```bash
# 对话 / 问答
LLM_BASE_URL=...   LLM_API_KEY=...   LLM_MODEL=...
# 文本向量化（BASE_URL / API_KEY 留空则回退 LLM 同款，见 M01 §5.3）
EMBED_BASE_URL=    EMBED_API_KEY=    EMBED_MODEL=...
```

**其余分组**：

| 分组 | 字段 |
|---|---|
| 运行 | `DEBUG`、`VERSION` |
| 多模型种子 | `MODEL_PROFILES`（JSON 数组；仅在 `model_profiles` 表为空时注入一次） |
| 摄取过滤 | `INGEST_EXTS`（默认 `md,txt`）、`INGEST_EXCLUDE_DIRS`（默认排除 `node_modules` / `.git` / `.obsidian` / `.trash` / `__pycache__` / `.venv`） |
| 变更管理 | `INGEST_SYNC_INTERVAL`（定时同步秒数，0=关）、`INGEST_SYNC_ON_STARTUP`、`INGEST_SETTLE_SECONDS`、`INGEST_MAX_CONCURRENCY`、`PRUNE_ENABLED`、`PRUNE_RATIO_LIMIT`（默认 0.5）、`SYNC_RUNS_KEEP`（默认 50）、`PROGRESS_FLUSH_MS`（进度落库最小间隔，默认 500；阶段跳变与终态强制写）、`WATCH_ENABLED`、`WATCH_DEBOUNCE_MS`、`MAX_FILE_SIZE`（详见 M03 §8 / M01 §5.2） |
| 存储 | `CHROMA_DIR`、`SQLITE_PATH` |
| 服务 | `API_KEY`、`CORS_ORIGINS`、`HOST`、`PORT`、`PUBLIC_BASE_URL` |
| 多用户 / 前端 | `ENABLE_MULTIUSER`（默认 false）、`JWT_SECRET`、`UPLOAD_DIR`、`UI_ENABLED` |
| 日志 | `LOG_LEVEL`、`LOG_FILE`、`LOG_ROTATION`、`LOG_RETENTION`、`LOG_ERROR_FILE` |

**四条容易踩的配置规则**：

1. **列表字段支持两种写法**：`INGEST_EXTS` / `INGEST_EXCLUDE_DIRS` / `MODEL_PROFILES` 用 `Annotated[List[str], NoDecode]` + 自定义校验器，逗号分隔或 JSON 数组都行，空值返回 `[]`（pydantic-settings 默认会先做 JSON 解码，写 `a,b` 会直接 `SettingsError` 崩溃 —— 详见 M01 §5.2）。
2. **DB 是唯一运行时真相源**：`vaults` / `model_profiles` 表为准。**vault 完全由 DB/API/前端运行时配置，`.env` 不提供 vault 种子**（首次启动 `vaults` 表为空即无 vault，需通过前端或 `POST /vaults` 添加）；`model_profiles` 仍保留 `.env` 的 `MODEL_PROFILES` 作为一次性种子（表空时注入）。
3. **`HOST` 默认 `127.0.0.1`**；容器 / 服务端部署必须显式覆盖为 `0.0.0.0`，且**必须**置于反向代理 + HTTPS + API Key 之后。
4. **删除是一项被护栏约束的操作**：`vault` 文件被删除后，同步时会在三道护栏（源可达 / 扫描完整 / 删除比例 ≤ `PRUNE_RATIO_LIMIT`）通过后才清理索引；想只读镜像（永不删）就把 `PRUNE_ENABLED=false`。详见 M03 ADR-7。

**其他约定**：`.env` 不提交版本库；API Key 用常量时间比对（`hmac.compare_digest`）；出参永不返回明文模型密钥（只给掩码）。

---

## 9. 开发里程碑（建议顺序，逐步可跑）

| Phase | 内容 | 完成标志 |
|:---:|---|---|
| **0** | 脚手架：`main` + `config` + `database` + `healthz` | 服务起得来，`/docs` 可见，`/healthz` 返回 ok |
| **1** | 摄取：`chunker` + `embedder` + `vectorstore` + `ingest_service` + `/ingest` + **异步作业骨架**（`run_service` / `sync_runs` 进度列） | `curl /ingest` 拿 `202 + run_id`；轮询进度到终态，SQLite 与 Chroma 有数据 |
| **2** | 检索：`retrieval_service` + `/search` | `curl /search` 返回合理命中 |
| **3** | 问答：`llm_client` + `chat_service` + `/chat`（SSE）+ 鉴权中间件 | 收到 SSE 流，末尾带 sources，历史落库 |
| **4** | 持久化与测试：`note_repo` + `conversation_repo` + `tests/` + 结构化日志 | `pytest` 绿 |
| **5** | Vault 实体化 + 多用户 | 前端可增删 vault；`ENABLE_MULTIUSER=true` 时 login 通 |
| **6** | 前端 SPA | 六个页面（含**任务与进度** `/tasks`）可用，产物由后端同源托管 |
| **7** | 多模型管理 | 多 LLM / 多 Embedding 可选，切换生效 |
| **8** | Agent 接入（MCP） | 四个 tools 可调用，结果与 REST 一致 |
| **9** | 部署（Docker / 反代 / 远程加固） | 容器可用，数据持久化，远程访问经 HTTPS + API Key |

> 每个 Phase 结束都应能 `curl` 跑通对应接口，再进下一阶段。优先级的依赖关系与排序理由见设计文档库 `README.md` §3。

---

## 10. 全局约定

### 10.1 测试与质量

- **默认全部离线**：`embedder` / `llm_client` / 向量库在单测中全部替换为确定性替身；**测试不得要求真实 API Key**。
- **分层**：L1 纯函数 → L2 service 编排（mock rag 层）→ L3 `TestClient` 集成 → L4 安全（401 / 越权）→ L5 冒烟（起服务 + `/healthz`）。
- **质量门禁**：`compileall` → 导入自检 → `pytest` → 配置解析回归 → 冒烟 → 密钥泄漏扫描。
- 集成测试使用临时目录 + 自造样本 vault，**不得**写入仓库 `./data`、不得使用真实笔记。
- 完整方法论、门禁清单与回归清单见 **附录 A 测试策略与质量保障**。

### 10.2 风险与注意（全局）

| 风险 | 说明与应对 |
|---|---|
| embedding 维度 / 模型必须与索引一致 | 换模型必须重建索引；接口层不暴露检索用 embedding（M04 §5.3） |
| LLM 流式中断 | 优雅收尾并保存已生成消息，避免对话历史残缺（M05 §5.5） |
| 大 vault 的内存 / 耗时 | 限制单次扫描文件数、分批 embedding、设 `max_file_size`（M03 §9） |
| 索引类操作超时 / 客户端断连 | **一律异步作业**：接口 `202 + run_id` 立即返回，执行在后台协程；**不要**给索引接口加同步等待或 `wait` 参数（漏 `shield` 即等于「超时静默取消任务」，M03 ADR-12） |
| 同 vault 并发索引 | `run_service` 用内存锁串行化，同库重复提交返回 `409 + existing_run_id`（**不排队**，M06 ADR-8）。该锁**仅单进程有效** → 一期按**单 worker** 部署（M10）；多副本需换 DB 行锁 + 文件锁（M03 §12 未决） |
| 进程崩溃留下僵尸作业 | 启动时 `run_service.recover_stale()` 把残留 `queued` / `running` 标为 `aborted`，**不做断点续跑**（sync 幂等，重跑比持久化中间态简单）。不清的话「该库是否有作业在跑」的判断会被永久阻塞（M03 §5.13.6） |
| 索引失败 / 取消后的模型状态 | `vaults.embed_profile_id` / `embed_indexed_profiles` **只在作业成功（success / partial）后回写**；否则 vault 会谎称「已用某模型建好索引」而 collection 里没有向量，检索**静默返回空结果**（M06 ADR-9） |
| Chroma 版本兼容 | `uv.lock` 锁定；`pyproject.toml` 用 `^` 约束主版本；Intel Mac 需在 `[tool.uv] required-environments` 锁定平台（避开 onnxruntime 无 x86_64 wheel 的坑） |
| `.env` / `data/` 不入版本库 / 不进镜像 | `.gitignore` + `.dockerignore`；Docker 用 `--env-file` |
| 远程访问裸奔 | 强制 API Key + HTTPS + CORS 收紧 + 路径白名单（M10 §5.4 检查单） |

### 10.3 开源与可扩展性约定

- 项目以 **MIT 协议**开源，**不限制使用场景**：个人、团队、商业自托管均可。
- 分层架构保证任一环节可替换、可扩展：
  - **向量库**：Chroma → pgvector / Qdrant / Milvus（实现 `VectorStore` 抽象即可）
  - **LLM / Embed**：OpenAI 兼容 → 任意兼容端点（仅改 `base_url` / `api_key`）
  - **关系库**：SQLite → Postgres（改 engine URL 与 driver 即可，ORM 不变）
  - **文件格式**：新增 parser 即支持新格式（不改 RAG 管线，见 M11）
- **多租户 / 多 vault**：通过数据模型预留的 `user_id` / `vault_id` 列 + 鉴权中间件透传实现（见 M02 / M06）。
- 欢迎社区贡献：新检索策略（reranker / 混合检索）、新向量后端、前端、部署模板（Docker / compose / Helm）等。
- **部署模板已内置**：`deploy/` 提供 Dockerfile / docker-compose.yml / nginx 示例，本地与服务端共用同一套代码与配置。
- 提交规范、PR 流程见仓库根 `CONTRIBUTING.md`。

---

## 11. 模块设计文档索引

模块级方案已拆分为独立文档，按**实现优先级**排列。文档库位置：`personal-lib/00-Projects/notes-rag-design/`。

### 11.1 模块文档（按优先级）

| 编号 | 模块 | 优先级 | 覆盖内容 |
|:---:|---|:---:|---|
| M01 | 基础框架与配置 | **P0** | `Settings` 全字段、列表字段解析、数据库引擎、安全原语、应用装配、依赖注入、日志中间件 |
| M02 | 数据模型与持久化 | **P1** | ORM 8 张表（含 `sync_runs`）、索引与约束、隔离策略、schemas 清单、note / conversation repo |
| M03 | 摄取管线 | **P2** | 解析器契约、过滤三层合并、分块策略、嵌入、向量写入、文件级原语（`index_file` / `drop_file` / `move_file`）；**变更管理**（增量对账、删除三护栏、`sync_runs`、`doctor`）；**作业化执行与进度可视化**（异步作业模型、阶段进度、节流上报、协作式取消） |
| M04 | 检索服务 | **P3** | `retrieve` 契约、向量查询语义、embedding 一致性守卫、阈值与参数调优 |
| M05 | 问答服务（SSE） | **P4** | Prompt 模板、上下文组装、SSE 事件协议、落库时机、防幻觉 |
| M06 | Vault 实体化与多用户鉴权 | **P5** | vault 权威性模型、来源类型、上传安全、reindex、多用户开关与升级路径 |
| M07 | 前端 SPA | **P6** | 页面职责、API 客户端与 SSE 消费、**任务与进度视图**（进度条两形态、阶段中文化、取消交互、轮询策略）、构建与同源托管、多阶段构建 |
| M08 | 多模型管理 | **P7** | `model_profiles`、LLM/Embedding 差异约束、三级解析、collection 命名、种子注入 |
| M09 | Agent 接入（MCP / Skill） | **P8** | MCP tools 封装、stdio / Streamable HTTP 取舍、客户端配置、Skill 补充 |
| M10 | 部署方案 | **P9** | 本地 / Docker、数据卷、反代要点、远程访问强制检查单、容量估算 |
| M11 | 多格式解析与过滤 | **P10** | 类型矩阵、各格式解析要点、可选依赖、启用路径（仅契约·预留） |
| 附录 A | 测试策略与质量保障 | 贯穿 | 测试分层、mock 契约、样本数据、质量门禁、回归清单 |

### 11.2 参考资料（非模块设计）

| 文档 | 内容 |
|---|---|
| `requirements.md` | 需求清单与范围边界（FR 编号来源） |
| `libs-comparison.md` | 候选库横向对比与选型依据 |
| `vector-rag-embedding.md` | 向量库 / Embedding 模型 / RAG 检索方略详解（M03 / M04 的细化依据） |
| `demo/index.html` | 全模块可交互 Web Demo（对齐设计与交互预期） |

### 11.3 原章节 → 模块文档 映射（历史坐标）

> 代码注释中存在的 `docs/design.md §X` 引用依赖下表解析；`§` 编号自此为**历史坐标**，新增内容一律直接写进对应模块文档，不再回填编号体系。

| 原章节 | 现归属 |
|---|---|
| §1 架构总览 / §3 技术选型 / §13 开源约定 | **本文**（§2 / §4 / §10.3） |
| §2 目录结构 | **本文** §3（模块内文件清单见各模块 §4） |
| §4 数据流与时序 | **本文** §5（骨架）；明细：§4.1 → M03、§4.2 → M04、§4.3 → M05 |
| §5 API 设计 | **本文** §6（总览）；明细见各模块 |
| §6 数据模型 | **本文** §7（总览）；字段级 → M02 |
| §7 RAG 管线设计 | 分块 / 嵌入 → M03；检索 → M04；Prompt / 流式 → M05 |
| §8 配置与安全 | **本文** §8（总览）；配置语义 → M01；安全原语 → M01 §9；出参脱敏 → M08 §9 |
| §9 开发里程碑 | **本文** §9 |
| §10 手写 TODO 地图 | 按阶段拆入 M01–M08 的「详细设计 · 接口契约」 |
| §11 测试策略 | **附录 A** |
| §12 风险与注意 | **本文** §10.2（汇总）＋ 各模块「风险与未决问题」 |
| §14 Agent 接入方案 | **M09** |
| §15 部署方案 | **M10** |
| §16 多格式与过滤 | 契约 / 过滤 → M03 §5.1 / §5.3；格式矩阵与启用路径 → **M11** |
| §17.1 / §17.6 前端 | **M07** |
| §17.2 / §17.3 / §17.4 / §17.5 Vault 与多用户 | **M06** |
| §18 多模型管理 | **M08** |
| **变更管理**（vault 文件新增 / 删除 / 修改 / 改名如何管理；原设计未覆盖） | 方案主体 **M03 §5.8–§5.12**；表与字段 **M02 §5.1**；入口 **M06 §5.3 / §5.5**；交互 **M07 §5.2** |
| **作业化执行与进度可视化**（提交 → `202 + run_id` → 轮询 / 取消；原设计为同步返回汇总） | 方案主体 **M03 §5.13**（含 ADR-12 全异步 / ADR-13 进度节流 / ADR-14 协作式取消）；表与字段 **M02 §5.1**；提交语义、`409` 不排队、模型状态回写在成功后 **M06 §5.3 / §5.5**（ADR-8 / ADR-9）；交互契约 **M07 §5.4** |

---

## 12. 变更记录

| 日期 | 版本 | 变更摘要 |
|---|---|---|
| 2026-09-24 | v2.3 | **全异步作业模型**：写入类端点一律 `202 + run_id`（否决同步返回与 `wait` 参数）；§5.1 / §5.1.1 数据流改为「提交作业 → 后台推进」；§6 接口总览补 `runs/{rid}` 与 `cancel` 并去掉重复行，新增 `202` / `409` 不排队 / 取消用 `POST` 的契约说明；§7 数据模型补 `sync_runs` 进度列与七态；§8 配置补 `PROGRESS_FLUSH_MS`；§9 里程碑 Phase 1 含作业骨架、Phase 6 六个页面；§10.2 补 4 行风险（超时/断连、同库并发、僵尸作业、模型状态回写）；§11 登记 **M03 §5.13**（含 ADR-12/13/14）与 **M07 §5.4** |
| 2026-09-23 | v2.0 | 拆分为「大纲（本文）+ 11 个模块文档 + 附录 A」；本文保留项目简介、架构、目录、选型、数据流 / 接口 / 数据模型 / 配置总览、里程碑、全局约定与模块索引；模块级方案迁至 `notes-rag-design/modules/` |
| 2026-09-23 | v2.1 | 增补**变更管理**索引：§5.1.1 同步流程骨架、§6 接口总览增 `sync` / `runs` / `doctor`、§7 数据模型总览更新表数、模块索引与映射表登记变更管理归属（方案主体 M03 §5.8–§5.12） |
| 2026-09-23 | v2.2 | vault 配置模型变更：配置总览删 `VAULT_SOURCES` 行；三条配置规则第 1/2 条更新（vault 完全运行时配置，.env 不提供种子；model_profiles 仍保留种子） |
| 2026-09-22 | v1.x | 新增 §16 多格式与过滤、§17 前端 / Vault / 多用户、§18 多模型管理 |
