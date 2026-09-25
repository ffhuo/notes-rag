# notes-rag

> 知识库智能应用（RAG）—— 把 Markdown / 纯文本笔记（Obsidian vault 或任意目录）变成可检索、可问答的 **Web 应用**（后端 API + 前端页面）。
> vault 在前端页面配置（添加本地目录 / 上传 vault 压缩包），是否支持多用户由配置开关决定（默认单用户）。
> 可配置**多个 LLM / 多个 Embedding**并在使用时选择：LLM 每次请求可换；Embedding 与索引绑定，换模型需重建索引（详见设计文档库 **M08 多模型管理**）。
> 一期支持 `.md` / `.txt`；PDF / Word / Excel 等多格式解析与文件/文件夹过滤已在设计层预留（详见 **M11 多格式解析与过滤**）。
> 本项目提供分层架构骨架与完整方案文档：`docs/design.md` 是**大纲与基础介绍**（架构 / 目录 / 选型 / 总览 / 里程碑 / 全局约定 / 模块索引），**模块级详细方案**在 `personal-lib/00-Projects/notes-rag-design/` 下按实现优先级排列。业务逻辑可按这些文档手写实现，适合练手，也适合作为自托管知识库服务直接部署。

## 交互 Demo（不写代码也能看到全貌）

`demo/index.html` 是一个**零依赖单文件原型**：内置模拟后端，可在浏览器里直接操作全部模块——架构分层、配置中心（LLM / Embedding 分离与回退）、**模型管理（多 LLM / 多 Embedding、切换 embedding 需重建索引的报错演示）**、Vault 管理、摄取（过滤 + 解析器路由）、检索、SSE 问答、多用户切换与隔离、MCP tools 调用、本地 / Docker 部署与健康检查。

```bash
make demo      # 直接打开 demo/index.html
# 或：open demo/index.html
```

> 后端业务逻辑目前仍为 `...` 占位（按 `docs/design.md` §9 的 Phase 0 → 9 手写），Demo 用于对齐设计与交互预期，不代表真实后端行为。

## 技术栈

- FastAPI + Uvicorn（异步 Web 框架）
- Pydantic v2 + pydantic-settings（校验与配置）
- SQLAlchemy 2.0 (async) + aiosqlite（元数据 / 对话历史）
- Chroma（本地持久化向量库）
- openai SDK（兼容端点，可指向 Qwen / 任意 OpenAI 兼容服务）
- **Vue 3 + Vite**（前端 SPA：Vault 管理 / 检索 / 问答 / 模型管理，见设计文档库 M07 前端 SPA）
- **uv**（Rust 实现的极速 Python 包管理器，遵循标准 PEP 621）

## 目录结构

```
notes-rag/
├── docs/
│   └── design.md            # 开发方案设计·大纲（架构 / 目录 / 选型 / 总览 / 里程碑 / 全局约定 / 模块索引）
│   # 模块级详细设计（M01–M11 + 附录 A）与需求/选型/RAG 详解：
│   # personal-lib/00-Projects/notes-rag-design/（modules/ 下按实现优先级排列）
├── app/
│   ├── main.py              # FastAPI 入口（你手写）
│   ├── api/                 # 路由层（ingest / search / chat / vaults / auth / models）
│   ├── core/                # config / security（API Key + JWT）/ database
│   ├── services/            # 业务分层（run = 作业层 / sync = 对账层 / ingest = 原语层 / retrieval / chat / vault / model / watcher）
│   ├── repositories/        # 数据访问（note / conversation / vault / model / sync_runs 作业记录）
│   ├── models/              # Pydantic schemas + ORM（users / vaults / model_profiles / notes / chunks / conversations / messages / sync_runs）
│   ├── rag/                 # chunker / embedder / vectorstore / llm_client
│   ├── parsers/             # 多格式解析层（md/txt 一期，pdf/docx/xlsx 预留，见 M03 / M11）
│   ├── mcp/                 # MCP server（Agent 接入，见 M09）
│   └── static/              # 前端构建产物（由 frontend/ 构建产出，gitignore）
├── frontend/                # 新增：Vue 3 + Vite SPA 源码（Vault 管理 / 检索 / 问答，见 M07）
├── tests/                   # 单测 / 集成测试
├── scripts/                 # 建表等脚本
├── deploy/                  # 部署模板（多阶段 Docker / compose / nginx，见 M10 部署方案 / M07 前端构建）
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── nginx.conf.example
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

（可选）国内加速：若 `uv sync` 下载慢，先配置清华镜像再安装：
`export UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`

```bash
cd notes-rag

# 1. 解析并安装依赖、创建项目内虚拟环境（./.venv），写入 uv.lock
uv sync --python 3.12

# 2. 配置环境变量
cp .env.example .env        # 填入 LLM_API_KEY / VAULT_PATH 等

# 3. 按 docs/design.md §9 的 Phase 0 → Phase 9 逐步手写代码
```

> 当前 `.venv` 已在本机用 `uv sync` 安装完成并验证（`uv run python -c "import fastapi, chromadb"` 通过）。

`uv sync` 之后所有命令用 `uv run` 前缀（自动激活 .venv）：

```bash
uv run python -m app.main
uv run uvicorn app.main:app --reload
uv run pytest
```

## 启动（代码写完后）

### 本地运行

```bash
# 方式一：模块方式
uv run python -m app.main

# 方式二：uvicorn（推荐，支持热重载）
uv run uvicorn app.main:app --reload
```

交互式文档：启动后访问 `http://127.0.0.1:8000/docs`

### Docker 部署（服务端 / 远程访问）

```bash
# 构建并启动（数据持久化到 ./data，监听 0.0.0.0）
make docker-build
make docker-up          # 等价于 docker compose -f deploy/docker-compose.yml up -d --build

# 或直接使用 docker run
docker run -d --name notes-rag -p 8000:8000 \
  -v $(pwd)/data:/app/data --env-file .env -e HOST=0.0.0.0 notes-rag
```

- 远程访问必须经**反向代理 + HTTPS + API Key**（详见 M10 部署方案的远程访问强制检查单）。
- 数据卷、vault 远程导入、Nginx 反代模板见 M10 部署方案。
- Docker 镜像为**多阶段构建**：先构建前端（node）再打 Python 镜像，前端静态由后端同源托管（见 M07 前端 SPA）。

### 前端页面（Vue 3 + Vite SPA）

前端源码在 `frontend/`，提供 **Vault 管理 / 任务与进度 / 检索 / 问答 / 模型管理 / 登录** 页面（见 M07 前端 SPA）。
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

vault 完全由前端 / API 运行时配置，**不在 `.env` 中管理**：在前端「Vaults」页可**添加本地目录**（填绝对路径）或**上传 vault 压缩包（.zip）**，落 `vaults` 表。无前端时通过 `POST /api/v1/vaults` 或 CLI `make ingest`（一次性摄取）配置（见 M06 Vault 实体化与多用户鉴权）。

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

模型配置落 `model_profiles` 表（`.env` 的 `LLM_*` / `EMBED_*` 只是首次启动的种子），前端「Models」页可增删改、设默认、试连。

- **LLM**：无状态耦合，**每次请求都能换**（`ChatRequest.llm_profile`，前端问答页下拉选择）。
- **Embedding**：与索引强绑定 —— 向量按 `v{vault}_m{profile}` 分集合，检索必须沿用建索引时那个模型；换模型 = 对该 vault 重新索引（`POST /vaults/{id}/reindex?embed_profile=...`）。接口**故意不暴露** `SearchRequest.embed_profile`，避免「能召回但全是噪声」的静默错误。

详见设计文档库 M08 多模型管理。

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
| `make install` | 安装依赖并创建 `.venv`（`uv sync --python 3.12`） |
| `make dev` | 热重载启动开发服务器（uvicorn，端口 8000） |
| `make run` | 直接运行（`python -m app.main`） |
| `make test` | 运行 pytest |
| `make init-db` | 初始化 SQLite 表 |
| `make ingest` | 提交 `/ingest` 索引作业（需先 `make dev`；`API_KEY` / `VAULT_SOURCES` 用环境变量传入，拼进请求体，非 `.env` 配置项）。返回 `202 + run_id`，进度在「任务」页或 `GET /vaults/{id}/runs/{rid}` 查 |
| `make clean` | 清理运行时数据与缓存 |
| `make shell` | 进入 venv 的 python REPL |
| `make frontend-install` | 安装前端依赖（`frontend/`） |
| `make frontend-dev` | 前端热重载开发（Vite，代理 `/api` 到 `:8000`） |
| `make frontend-build` | 构建前端到 `app/static`（由后端托管） |
| `make docker-build` | 构建镜像（多阶段：含前端构建） |
| `make docker-up` | 用 docker compose 启动 |

> 查看全部命令：`make help`。`make ingest` 示例（`VAULT_SOURCES` 是传给 API 的请求体参数，非 `.env` 配置）：
> `export API_KEY=xxx VAULT_SOURCES="local:/path/to/vault" && make ingest`

## Agent 接入（MCP / Skill）

项目可被 agent（WorkBuddy、OpenClaw 等）当作知识库工具调用，方案见 **设计文档库 M09 Agent 接入（MCP / Skill）**：

- **MCP server（主线）**：`app/mcp/server.py` 把检索 / 问答封装为标准 MCP tools，由 agent 通过 `mcp.json` 配置接入；支持 **stdio（本地零端口推荐）** 与 **Streamable HTTP（服务端部署后远程 agent 接入）** 两种传输。
- **Skill（零部署补充）**：可额外提供 `skill/SKILL.md`，让任意支持 skill 的 agent 通过文本指令调 REST。
- **两种运行形态**：本地模式数据全在本机、MCP 用 stdio 最省事；服务端部署（Docker）对外提供远程访问，MCP 走 Streamable HTTP + API Key（详见 M09 / M10 部署方案）。启用前 `uv sync`（pyproject 已加 `mcp`）。

## 文档

**代码仓库内**：

- [开发方案设计·大纲](docs/design.md) —— 架构、目录结构、技术选型、数据流 / 接口 / 数据模型 / 配置总览、里程碑、全局约定、**模块文档索引（含原章节 → 模块文档映射表）**
- [贡献指南](CONTRIBUTING.md)
- 许可证：MIT（见 [LICENSE](LICENSE)）
- 交互 Demo：[demo/index.html](demo/index.html)

**设计文档库**（`personal-lib/00-Projects/notes-rag-design/`，模块级方案按实现优先级排列）：

- [设计文档总览与索引](../../personal-lib/00-Projects/notes-rag-design/README.md)
- [需求清单与范围边界](../../personal-lib/00-Projects/notes-rag-design/requirements.md)
- [基础库选型对比（log/config/database）](../../personal-lib/00-Projects/notes-rag-design/libs-comparison.md)
- [向量库·Embedding 模型·RAG 检索方略详解](../../personal-lib/00-Projects/notes-rag-design/vector-rag-embedding.md)
- 模块文档 `modules/`：`01` 基础框架配置 · `02` 数据模型 · `03` 摄取管线 · `04` 检索 · `05` 问答 SSE · `06` Vault 与多用户 · `07` 前端 SPA · `08` 多模型 · `09` Agent MCP · `10` 部署 · `11` 多格式 · `appendix-a` 测试策略
