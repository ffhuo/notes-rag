# notes-rag

English | [简体中文](README.md)

> 知识库智能应用（RAG）—— 把 Markdown / 纯文本笔记（Obsidian vault 或任意目录）变成可检索、可问答的 **Web 应用**（后端 API + 前端页面）。
> vault 在前端页面配置（添加本地目录 / 上传 vault 压缩包），是否支持多用户由配置开关决定（默认单用户）。
> 可配置**多个 LLM / 多个 Embedding**并在使用时选择：LLM 每次请求可换；Embedding 与索引绑定，换模型需重建索引（多模型设计要点见 `docs/design.md` 模块索引 M08）。
> 已支持 `.md` / `.txt` / `.docx` / `.pdf` / `.xlsx` 解析（PDF 扫描件走多模态 LLM 识别）与文件/文件夹过滤（设计概要见 `docs/design.md` 模块索引 M11）。
> 本项目提供分层架构与**设计大纲**：`docs/design.md`（架构 / 目录 / 选型 / 数据流 / 接口 / 数据模型 / 配置总览 / 全局约定 / 模块索引），业务逻辑可按文档逐步实现，适合练手，也适合作为自托管知识库服务直接部署。

> 后端业务逻辑已完成实现（路由 / 服务 / 仓储 / RAG 分层齐全），Demo 仅用于零依赖预览交互，实际行为以真实后端为准。

## 技术栈

- FastAPI + Uvicorn（异步 Web 框架）
- Pydantic v2 + pydantic-settings（校验与配置）
- SQLAlchemy 2.0 (async) + aiosqlite（元数据 / 对话历史；SQLite 开启 WAL）
- Chroma（本地持久化向量库，集合按 `v{vault}_m{profile}` 隔离）
- openai SDK（兼容端点，可指向任意 OpenAI 兼容服务）
- python-docx + PyMuPDF + openpyxl（`.docx` / `.pdf` / `.xlsx` 解析）；Pillow（本地图片尺寸 / 格式校验）
- loguru（结构化日志，支持轮转、保留与级别配置）
- MCP Python SDK（FastMCP，Agent 接入见 `docs/mcp-guide.md`）
- **Vue 3 + Vite**（前端 SPA：Vault 管理 / 任务 / 检索 / 问答 / 模型管理，设计概要见 `docs/design.md` 模块索引 M07）
- **uv**（Rust 实现的极速 Python 包管理器，遵循标准 PEP 621）；测试用 pytest + pytest-asyncio

## 目录结构

```
notes-rag/
├── docs/
│   ├── design.md            # 开发方案设计·大纲（架构 / 目录 / 选型 / 总览 / 全局约定 / 模块索引）
│   ├── mcp-guide.md         # MCP 接入使用说明（效果 / 三步接入 / 排错）
│   ├── README_EN.md         # English README
│   ├── DESIGN_EN.md         # English design overview
│   └── MCP_GUIDE_EN.md      # English MCP guide
├── app/
│   ├── main.py              # FastAPI 入口：装配路由 / 中间件 / 前端静态托管，生命周期建表 + 清理残留作业
│   ├── api/                 # 路由层（health / ingest / search / chat / conversations / audio / vaults / auth / models）
│   ├── core/                # config / security（API Key + JWT）/ database（异步引擎 + 建表）/ middleware（请求日志）
│   ├── services/            # 业务分层（run = 作业层 / sync = 对账层 / ingest = 原语层 / retrieval / chat / vault / model / image / watcher）
│   ├── repositories/        # 数据访问（note / conversation / vault / model / sync_runs / image）
│   ├── models/              # Pydantic schemas + ORM（users / vaults / model_profiles / notes / chunks / conversations / messages / sync_runs / image_cache）
│   ├── rag/                 # chunker / embedder / vectorstore / llm_client / client（build_client 为唯一构造入口）
│   ├── parsers/             # 多格式解析层（md/txt/docx/pdf/xlsx 已实现，见 M03 / M11）
│   ├── mcp/                 # MCP server（FastMCP，stdio / Streamable HTTP，见 M09）
│   └── static/              # 前端构建产物（由 frontend/ 构建产出，gitignore）
├── frontend/                # Vue 3 + Vite SPA 源码（Vault / 任务 / 检索 / 问答 / 模型，见 M07）
├── tests/                   # 单测 / 集成测试（解析器 / 分块 / 嵌入 / 摄取 / 图片 / vault 删除）
├── scripts/                 # init_db.py 建表脚本
├── deploy/                  # 部署模板（多阶段 Docker / compose / nginx，见 M10 部署方案 / M07 前端构建）
│   ├── Dockerfile           # 多阶段：node 构建前端 → python:3.12-slim + uv，单镜像同源托管
│   ├── docker-compose.yml   # 单服务 + 数据/日志卷 + healthcheck
│   └── nginx.conf.example   # 反向代理 + TLS 示例（含 SSE 关闭缓冲）
├── data/                    # 运行时数据（向量库 + sqlite，已 gitignore）
├── pyproject.toml           # PEP 621 依赖清单（标准格式）
├── uv.lock                  # 锁定后的依赖版本（uv lock 生成，需提交）
├── .env.example
├── .dockerignore
└── .gitignore
```

## 环境准备（uv）

> 本机需先安装 uv（任选其一）：
> - `python -m pip install uv`
> - 或官方脚本：`curl -LsSf https://astral.sh/uv/install.sh | sh`
> 本机 Python 命令约定：统一用 `python`（3.12）。

**依赖默认从官方 PyPI 安装**；国内网络可指定镜像加速：
`make sync UV_INDEX=https://mirrors.aliyun.com/pypi/simple/`（`Makefile` 会把它注入 `UV_DEFAULT_INDEX`，优先级高于配置文件；个人偏好也可放未入库的 `uv.toml`）。
> 注意：清华 TUNA 镜像近期存在 403 无法下载 wheel 的问题，不建议使用。

```bash
cd notes-rag

# 1. 解析并安装依赖、创建项目内虚拟环境（./.venv），写入 uv.lock
make install            # 等价于 uv sync --python 3.12

# 2. 配置环境变量
cp .env.example .env    # 按需调整 API_KEY / 摄取过滤；模型配置在「模型」页配（.env 不再提供模型配置）

# 3. 初始化 SQLite 表（应用启动时也会自动建表，此命令用于手动补齐）
make init-db
```

`uv sync` 之后所有命令用 `uv run` 前缀（自动激活 .venv）：

```bash
uv run python -m app.main
uv run uvicorn app.main:app --reload
uv run pytest
```

## 启动

### 本地运行

```bash
# 方式一：模块方式
uv run python -m app.main

# 方式二：uvicorn（推荐，支持热重载）
uv run uvicorn app.main:app --reload
```

- 前端页面：`http://127.0.0.1:8000/`（需先 `make frontend-build` 产出 `app/static`）。
- 交互式文档：`http://127.0.0.1:8000/docs` —— **仅 `DEBUG=true` 时可用**（默认关闭，见 `app/core/config.py` 的 `docs_url` 开关）。

### Docker 部署（服务端 / 远程访问）

**单镜像、单容器、单端口**：前端由 Vite 构建后打进同一个镜像，再由 FastAPI 同源托管，**不需要额外的 nginx 容器**。

```bash
# 构建并启动（数据持久化到 ./data、日志到 ./logs，监听 0.0.0.0）
make docker-build
make docker-up          # 等价于 docker compose -f deploy/docker-compose.yml up -d --build
make docker-down        # 停止

# 或直接用 docker run
docker run -d --name notes-rag -p 8000:8000 \
  -v $(pwd)/data:/app/data -v $(pwd)/logs:/app/logs \
  --env-file .env -e HOST=0.0.0.0 notes-rag
```

镜像与 compose 要点：

| 项 | 说明 |
| --- | --- |
| 多阶段构建 | Stage 1 用 `node:20-alpine` 执行 `npm ci && npm run build`（产物落在 `app/static`）；Stage 2 用 `python:3.12-slim` + `uv sync --no-dev`，复制产物交 FastAPI 托管 |
| 端口 | 容器内 `8000`；`HOST=0.0.0.0` 由 compose 注入（本地默认 `127.0.0.1`） |
| 数据/日志卷 | `../data → /app/data`（Chroma + SQLite + uploads）、`../logs → /app/logs` |
| 健康检查 | `healthcheck` 探测 `/healthz`，`docker compose ps` 可看 healthy 状态 |
| 生产默认 | compose 强制 `DEBUG=false`（不暴露 `/docs`、不打印 SQL）；调试可在 compose 的 `environment` 覆盖 |

- 远程访问必须经**反向代理 + HTTPS + API Key**（详见 M10 部署方案的远程访问强制检查单）；模板见 [deploy/nginx.conf.example](deploy/nginx.conf.example)（已含 SSE 关闭缓冲配置）。
- 当 `UI_ENABLED=true` 且存在 `app/static` 时，后端挂载 `/assets` 静态资源，并对前端子路由（如 `/tasks`）做 SPA 兜底；`/api/*` 未命中仍返回 404。

### 前端页面（Vue 3 + Vite SPA）

前端源码在 `frontend/`，前端路由为 `/vaults`（Vault 管理）/ `/tasks`（任务与进度）/ `/search`（检索）/ `/chat`（问答）/ `/models`（模型管理）；**登录 / 注册 / 填 API Key 由全局弹窗处理，无独立登录页**（见 M07 前端 SPA）。
问答页支持**语音输入**（浏览器录音 → `POST /api/v1/audio/transcribe`，需先在「模型」页配置 `kind=asr` 的模型，否则返回 409）。
其中「任务」页（`/tasks`）是异步索引作业的观察入口：进度条会随阶段自适应（`scan` 阶段总量未知时显示滚动条而非假百分比）、
可按 vault / 状态筛选、可展开看同步计划与失败清单、可随时取消。

```bash
# 开发联调（前后端分离）：Vite dev 代理 /api → 后端 :8000
make frontend-install
make frontend-dev          # 打开 http://127.0.0.1:5173

# 构建前端到 app/static（由后端 FastAPI 托管，同源免 CORS）
make frontend-build
# 之后正常起后端即可访问 http://127.0.0.1:8000/
```

### Vault 配置与索引作业（前端管理）

vault 完全由前端 / API 运行时配置，**不在 `.env` 中管理**：在前端「Vaults」页可**添加本地目录**（填绝对路径）或**上传 vault 压缩包（.zip）**，落 `vaults` 表。无前端时用 API：`POST /api/v1/vaults` 建库 → `POST /api/v1/vaults/{id}/sync` 提交作业；一次性摄取走 `POST /api/v1/ingest`（请求体 `vault_sources: ["local:/abs/path"]`）（见 M06 Vault 实体化与多用户鉴权）。

**索引都是异步作业**（`POST /vaults/{id}/sync` / `/reindex` → `202 + run_id`）：

- 提交后立即返回，**不等跑完**（全量重建 2–10 min，同步返回必撞网关超时）；进度在「任务」页（`/tasks`）实时看，
  接口是 `GET /vaults/{id}/runs/{rid}`，前端 1s 轮询。
- **同步**（增量对账）：日常用，只处理变化的文件，通常数秒。支持「预览变更」——提交 `dry_run` 作业，
  作业停在 `plan_ready`，先看这次会动哪些文件再决定是否执行。
- **重建索引**（全量）：换 embedding / 改分块参数 / 索引疑似损坏时才用。
- 同一 vault 已有作业在跑时再次提交返回 **`409` + `existing_run_id`（不排队）**，前端会直接跳去那个任务的进度。
- 作业可随时取消（`POST .../cancel`）：**协作式**，会在当前文件处理完后停止（文件级替换是幂等单元，停在边界天然一致）。
- 状态七态，其中 `failed`（程序异常）/ `cancelled`（用户主动停止）/ `aborted`（进程崩溃残留）语义不同，排查时不可混淆。

### 多用户（可配置，默认关闭）

`.env` 的 `ENABLE_MULTIUSER`（默认 `false`）：

- **false（单用户）**：所有资源归 `user_id="default"`，接口用 `X-API-Key` 鉴权，前端无登录页（在设置填一次 API Key）。
- **true（多用户）**：启用 `users` 表 + JWT（`JWT_SECRET` 必填），前端出现 Login 页；受保护接口同时接受 `X-API-Key` 与 `Bearer <JWT>`，vault / 对话按用户隔离（见 M06）。

### 多模型（多个 LLM / 多个 Embedding，使用时可选）

模型配置（LLM / Embedding / ASR）全部落 `model_profiles` 表，**`.env` 不再提供模型配置**（无兜底项）；前端「Models」页可增删改、设默认、试连。

- **LLM**：无状态耦合，**每次请求都能换**（`ChatRequest.llm_profile`，前端问答页下拉选择）。
- **Embedding**：与索引强绑定 —— 向量按 `v{vault}_m{profile}` 分集合，检索必须沿用建索引时那个模型；换模型 = 对该 vault 重新索引（`POST /vaults/{id}/reindex?embed_profile=...`）。接口**故意不暴露** `SearchRequest.embed_profile`，避免「能召回但全是噪声」的静默错误。

详见 `docs/design.md` 模块索引 M08。

### 语音输入（可选，需配置 ASR 模型）

问答页可录音转写：浏览器 MediaRecorder 采集音频 → `POST /api/v1/audio/transcribe`。转写使用 `model_profiles` 中 `kind=asr` 的模型，**`.env` 无兜底**，未配置时接口返回 **409** 提示去「模型」页配置。

- 协议按 `params.protocol` 分流：`dashscope_native` 走 DashScope 原生 `multimodal-generation` 同步端点；其余（含缺省）走标准 `/audio/transcriptions`。
- 实测：硅基流动（`api.siliconflow.cn/v1` + `FunAudioLLM/SenseVoiceSmall`）走标准接口即可；阿里云百炼须用 `dashscope_native`，且浏览器默认产出的 `webm/opus` 可能被其拒绝（返回 400）。

### 图片索引（多模态，自动生效）

文档中的图片会随索引交给多模态模型生成描述，再回插正文参与检索与问答：

- **无独立开关**：仅当本次索引所用 LLM 配置带 `params.multimodal=true` 时才处理。
- 本地图片：宽高 ≥ 200px、单张 ≤ 5MB，路径须在 vault 根目录内；远程 `http(s)` 外链直接透传给模型，不下载、不校验。
- 结果按 `(user_id, content_key)` 缓存于 `image_cache` 表；远程 URL 内容变更不会自动感知，需重建索引。

## 依赖管理说明（uv）

| 操作 | 命令 |
| --- | --- |
| 新增运行时依赖 | `uv add fastapi` |
| 新增开发依赖 | `uv add --group dev pytest` |
| 删除依赖 | `uv remove fastapi` |
| 升级全部（重解析） | `uv lock --upgrade` |
| 仅重解析锁定 | `uv lock` |
| 安装 lock 中的依赖 | `uv sync` |

> 注意：`uv.lock` 应当提交到 Git，保证环境一致；`.venv/`、`data/`、`.env` 已被 `.gitignore` 忽略。
> uv 使用标准 PEP 621 格式，项目非可发布库，已在 `[tool.uv]` 设 `package = false`。

## Make 快捷命令

项目根已提供 `Makefile`，把常用操作封装为一行命令（`uv` 路径已做回退，无需手动配 PATH）：

| 命令 | 作用 |
| --- | --- |
| `make install` / `make sync` | 安装依赖并创建 `.venv`（`uv sync --python 3.12`；国内可加 `UV_INDEX=<镜像>`） |
| `make dev` | 热重载启动开发服务器（uvicorn，端口 8000） |
| `make run` | 直接运行（`python -m app.main`） |
| `make test` | 运行 pytest |
| `make init-db` | 初始化 / 补齐 SQLite 表 |
| `make clean` | 清理运行时数据与缓存 |
| `make shell` | 进入 venv 的 python REPL |
| `make frontend-install` | 安装前端依赖（`frontend/`） |
| `make frontend-dev` | 前端热重载开发（Vite，代理 `/api` 到 `:8000`） |
| `make frontend-build` | 构建前端到 `app/static`（由后端托管） |
| `make frontend-check` | 前端门禁：构建 + 令牌对比度 + 样式合规（CI 用） |
| `make frontend-tokens` | 导出主题令牌给小程序（rpx）/ RN（TS） |
| `make docker-build` | 构建镜像（多阶段：含前端构建） |
| `make docker-up` | 用 docker compose 启动 |
| `make docker-down` | 停止 compose 服务 |

> 查看全部命令：`make help`。
> 一次性摄取请直接调 API（`Makefile` 中 `ingest` 仅在 `.PHONY` 声明、**尚未提供实现**），提交后返回 `202 + run_id`，进度在「任务」页或 `GET /api/v1/vaults/{id}/runs/{rid}` 查：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ingest \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"vault_sources": ["local:/path/to/vault"]}'
```

## Agent 接入（MCP / Skill）

项目可被 agent（WorkBuddy、OpenClaw 等）当作知识库工具调用，接入方法见 **`docs/mcp-guide.md`**，设计概要见 `docs/design.md` 模块索引 M09：

- **MCP server（主线）**：`app/mcp/server.py` 把检索 / 问答封装为标准 MCP tools，由 agent 通过 `mcp.json` 配置接入；支持 **stdio（本地零端口推荐）** 与 **Streamable HTTP（服务端部署后远程 agent 接入）** 两种传输。
- **Skill（零部署补充）**：可额外提供 `skill/SKILL.md`，让任意支持 skill 的 agent 通过文本指令调 REST。
- **两种运行形态**：本地模式数据全在本机、MCP 用 stdio 最省事；服务端部署（Docker）对外提供远程访问，MCP 走 Streamable HTTP + API Key（详见 M09 / M10 部署方案）。启用前 `uv sync`（pyproject 已加 `mcp`）。

## 文档

**代码仓库内**：

- [开发方案设计·大纲](docs/design.md) —— 架构、目录结构、技术选型、数据流 / 接口 / 数据模型 / 配置总览、全局约定、模块文档索引
- [MCP 接入使用说明](docs/mcp-guide.md) —— 把个人知识库接入 WorkBuddy 等 AI 助手：签发用户级 API Key、配置 mcp.json、可用工具与效果示例、排错速查
- [贡献指南](CONTRIBUTING.md)
- 许可证：MIT（见 [LICENSE](LICENSE)）

**English documentation**：[README](docs/README_EN.md) · [Design Overview](docs/DESIGN_EN.md) · [MCP Guide](docs/MCP_GUIDE_EN.md)
