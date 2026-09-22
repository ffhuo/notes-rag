# notes-rag

> 知识库智能应用（RAG）—— 把 Markdown / 纯文本笔记（Obsidian vault 或任意目录）变成可检索、可问答的 **Web 应用**（后端 API + 前端页面）。
> vault 在前端页面配置（添加本地目录 / 上传 vault 压缩包），是否支持多用户由配置开关决定（默认单用户）。
> 可配置**多个 LLM / 多个 Embedding**并在使用时选择：LLM 每次请求可换；Embedding 与索引绑定，换模型需重建索引（见 `docs/design.md` §18）。
> 一期支持 `.md` / `.txt`；PDF / Word / Excel 等多格式解析与文件/文件夹过滤已在设计层预留（见 `docs/design.md` §16）。
> 本项目提供分层架构骨架与完整方案文档；业务逻辑可按 `docs/design.md` 手写实现，适合练手，也适合作为自托管知识库服务直接部署。

## 交互 Demo（不写代码也能看到全貌）

`demo/index.html` 是一个**零依赖单文件原型**：内置模拟后端，可在浏览器里直接操作全部模块——架构分层、配置中心（LLM / Embedding 分离与回退）、**模型管理（多 LLM / 多 Embedding、切换 embedding 需重建索引的报错演示）**、Vault 管理、摄取（过滤 + 解析器路由）、检索、SSE 问答、多用户切换与隔离、MCP tools 调用、本地 / Docker 部署与健康检查。

```bash
make demo      # 直接打开 demo/index.html
# 或：open demo/index.html
```

> 后端业务逻辑目前仍为 `...` 占位（按 design.md Phase 0 → 4 手写），Demo 用于对齐设计与交互预期，不代表真实后端行为。

## 技术栈

- FastAPI + Uvicorn（异步 Web 框架）
- Pydantic v2 + pydantic-settings（校验与配置）
- SQLAlchemy 2.0 (async) + aiosqlite（元数据 / 对话历史）
- Chroma（本地持久化向量库）
- openai SDK（兼容端点，可指向 Qwen / 任意 OpenAI 兼容服务）
- **Vue 3 + Vite**（前端 SPA：Vault 管理 / 检索 / 问答，见 `docs/design.md` §17）
- **uv**（Rust 实现的极速 Python 包管理器，遵循标准 PEP 621）

## 目录结构

```
notes-rag/
├── docs/
│   └── design.md            # 开发方案设计（架构、API、数据模型、RAG 管线、手写 TODO 地图）
│   # 补充设计文档（需求清单/库选型/RAG 详解）已迁至 personal-lib/00-Projects/notes-rag-design/
├── app/
│   ├── main.py              # FastAPI 入口（你手写）
│   ├── api/                 # 路由层（ingest / search / chat / vaults / auth / models）
│   ├── core/                # config / security（API Key + JWT）/ database
│   ├── services/            # 业务编排（ingest / retrieval / chat / vault / model）
│   ├── repositories/        # 数据访问（note / conversation / vault / model）
│   ├── models/              # Pydantic schemas + ORM（users / vaults / model_profiles / notes / chunks / conversations / messages）
│   ├── rag/                 # chunker / embedder / vectorstore / llm_client
│   ├── parsers/             # 多格式解析层（md/txt 一期，pdf/docx/xlsx 预留，见 §16）
│   ├── mcp/                 # MCP server（Agent 接入，见 design.md §14）
│   └── static/              # 前端构建产物（由 frontend/ 构建产出，gitignore）
├── frontend/                # 新增：Vue 3 + Vite SPA 源码（Vault 管理 / 检索 / 问答，见 §17）
├── tests/                   # 单测 / 集成测试
├── scripts/                 # 建表等脚本
├── deploy/                  # 部署模板（多阶段 Docker / compose / nginx，见 docs/design.md §15 / §17.6）
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

# 3. 按 docs/design.md 的 Phase 0 → Phase 4 逐步手写代码
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

- 远程访问必须经**反向代理 + HTTPS + API Key**（详见 `docs/design.md` §15.4）。
- 数据卷、vault 远程导入、Nginx 反代模板见 `docs/design.md` §15。
- Docker 镜像为**多阶段构建**：先构建前端（node）再打 Python 镜像，前端静态由后端同源托管（见 §17.6）。

### 前端页面（Vue 3 + Vite SPA）

前端源码在 `frontend/`，提供 **Vault 管理 / 检索 / 问答** 三个页面（见 `docs/design.md` §17.1）。

```bash
# 开发联调（前后端分离）：Vite dev 代理 /api → 后端 :8000
make frontend-install
make frontend-dev          # 打开 http://127.0.0.1:5173

# 构建前端到 app/static（由后端 FastAPI 托管，同源免 CORS）
make frontend-build
# 之后正常起后端即可访问 http://127.0.0.1:8000/
```

### Vault 配置（前端管理）

vault 不再只靠 `.env`：在前端「Vaults」页可**添加本地目录**（填绝对路径）或**上传 vault 压缩包（.zip）**，落 `vaults` 表；
对每个 vault 可「重建索引」。`.env` 的 `VAULT_SOURCES` 作为**系统种子 vault**（首次启动写入），与前端的 vault 合并生效（见 §17.2）。

### 多用户（可配置，默认关闭）

`.env` 的 `ENABLE_MULTIUSER`（默认 `false`）：

- **false（单用户）**：所有资源归 `user_id="default"`，接口用 `X-API-Key` 鉴权，前端无登录页（在设置填一次 API Key）。
- **true（多用户）**：启用 `users` 表 + JWT（`JWT_SECRET` 必填），前端出现 Login 页；受保护接口同时接受 `X-API-Key` 与 `Bearer <JWT>`，vault / 对话按用户隔离（见 §17.3）。

### 多模型（多个 LLM / 多个 Embedding，使用时可选）

模型配置落 `model_profiles` 表（`.env` 的 `LLM_*` / `EMBED_*` 只是首次启动的种子），前端「Models」页可增删改、设默认、试连。

- **LLM**：无状态耦合，**每次请求都能换**（`ChatRequest.llm_profile`，前端问答页下拉选择）。
- **Embedding**：与索引强绑定 —— 向量按 `v{vault}_m{profile}` 分集合，检索必须沿用建索引时那个模型；换模型 = 对该 vault 重新索引（`POST /vaults/{id}/reindex?embed_profile=...`）。接口**故意不暴露** `SearchRequest.embed_profile`，避免「能召回但全是噪声」的静默错误。

详见 `docs/design.md` §18。

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
| `make ingest` | 触发 `/ingest` 摄取 vault（需先 `make dev`；`API_KEY` / `VAULT_SOURCES` 用环境变量传入，旧字段 `VAULT_PATH` 兼容） |
| `make clean` | 清理运行时数据与缓存 |
| `make shell` | 进入 venv 的 python REPL |
| `make frontend-install` | 安装前端依赖（`frontend/`） |
| `make frontend-dev` | 前端热重载开发（Vite，代理 `/api` 到 `:8000`） |
| `make frontend-build` | 构建前端到 `app/static`（由后端托管） |
| `make docker-build` | 构建镜像（多阶段：含前端构建） |
| `make docker-up` | 用 docker compose 启动 |

> 查看全部命令：`make help`。`make ingest` 示例（本地 vault 用 `VAULT_SOURCES`，旧字段 `VAULT_PATH` 仍兼容）：
> `export API_KEY=xxx VAULT_SOURCES="local:/path/to/vault,git:https://.../vault.git" && make ingest`

## Agent 接入（MCP / Skill）

项目可被 agent（WorkBuddy、OpenClaw 等）当作知识库工具调用，方案见 [开发方案设计 §14](docs/design.md)：

- **MCP server（主线）**：`app/mcp/server.py` 把检索 / 问答封装为标准 MCP tools，由 agent 通过 `mcp.json` 配置接入；支持 **stdio（本地零端口推荐）** 与 **Streamable HTTP（服务端部署后远程 agent 接入）** 两种传输。
- **Skill（零部署补充）**：可额外提供 `skill/SKILL.md`，让任意支持 skill 的 agent 通过文本指令调 REST。
- **两种运行形态**：本地模式数据全在本机、MCP 用 stdio 最省事；服务端部署（Docker）对外提供远程访问，MCP 走 Streamable HTTP + API Key（详见 `docs/design.md` §14.7 / §15）。启用前 `uv sync`（pyproject 已加 `mcp`）。

## 文档

- [需求清单与范围边界](../../personal-lib/00-Projects/notes-rag-design/requirements.md)
- [开发方案设计](docs/design.md)
- Agent 接入方案（MCP / Skill，对接 WorkBuddy / OpenClaw）见 [开发方案设计 §14](docs/design.md)
- [基础库选型对比（log/config/database）](../../personal-lib/00-Projects/notes-rag-design/libs-comparison.md)
- [向量库·Embedding 模型·RAG 检索方略详解](../../personal-lib/00-Projects/notes-rag-design/vector-rag-embedding.md)
- [贡献指南](CONTRIBUTING.md)
- 许可证：MIT（见 [LICENSE](LICENSE)）
