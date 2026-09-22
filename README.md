# rag-as-api

> 知识库智能后端（RAG-as-API）—— 把 Markdown 笔记（Obsidian vault 或任意目录）变成可检索、可问答的 FastAPI 服务。
> 本项目提供分层架构骨架与完整方案文档；业务逻辑可按 `docs/design.md` 手写实现，适合练手，也适合作为自托管知识库服务直接部署。

## 技术栈

- FastAPI + Uvicorn（异步 Web 框架）
- Pydantic v2 + pydantic-settings（校验与配置）
- SQLAlchemy 2.0 (async) + aiosqlite（元数据 / 对话历史）
- Chroma（本地持久化向量库）
- openai SDK（兼容端点，可指向 Qwen / 任意 OpenAI 兼容服务）
- **uv**（Rust 实现的极速 Python 包管理器，遵循标准 PEP 621）

## 目录结构

```
rag-as-api/
├── docs/
│   ├── requirements.md      # 需求清单与范围边界
│   └── design.md            # 开发方案设计（架构、API、数据模型、RAG 管线、手写 TODO 地图）
├── app/
│   ├── main.py              # FastAPI 入口（你手写）
│   ├── api/                 # 路由层（routes/ 下各端点）
│   ├── core/                # config / security / database
│   ├── services/            # 业务编排（ingest / retrieval / chat）
│   ├── repositories/        # 数据访问（SQLite）
│   ├── models/              # Pydantic schemas + ORM
│   ├── rag/                 # chunker / embedder / vectorstore / llm_client
│   └── mcp/                 # 新增：MCP server（Agent 接入，见 design.md §14）
├── tests/                   # 单测 / 集成测试
├── scripts/                 # 建表等脚本
├── data/                    # 运行时数据（向量库 + sqlite，已 gitignore）
├── pyproject.toml           # PEP 621 依赖清单（标准格式）
├── uv.lock                  # 锁定后的依赖版本（uv lock 生成，需提交）
├── .env.example
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
cd rag-as-api

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

```bash
# 方式一：模块方式
uv run python -m app.main

# 方式二：uvicorn（推荐，支持热重载）
uv run uvicorn app.main:app --reload
```

交互式文档：启动后访问 `http://127.0.0.1:8000/docs`

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
| `make ingest` | 触发 `/ingest` 摄取 vault（需先 `make dev`；`API_KEY` / `VAULT_PATH` 用环境变量传入） |
| `make clean` | 清理运行时数据与缓存 |
| `make shell` | 进入 venv 的 python REPL |

> 查看全部命令：`make help`。`make ingest` 示例：
> `export API_KEY=xxx VAULT_PATH=/path/to/vault && make ingest`

## Agent 接入（MCP / Skill）

项目可被 agent（WorkBuddy、OpenClaw 等）当作个人知识库工具调用，方案见 [开发方案设计 §14](docs/design.md)：

- **MCP server（主线）**：`app/mcp/server.py` 把检索 / 问答封装为标准 MCP tools，由 agent 通过 `mcp.json` 配置接入；支持 stdio（个人用户零端口推荐）与 Streamable HTTP 两种传输。
- **Skill（零部署补充）**：可额外提供 `skill/SKILL.md`，让任意支持 skill 的 agent 通过文本指令调 REST。
- 个人用户取向：数据不出本机、零外部服务、配置极简；启用前 `uv sync`（pyproject 已加 `mcp`）。

## 文档

- [需求清单与范围边界](docs/requirements.md)
- [开发方案设计](docs/design.md)
- Agent 接入方案（MCP / Skill，对接 WorkBuddy / OpenClaw）见 [开发方案设计 §14](docs/design.md)
- [基础库选型对比（log/config/database）](docs/libs-comparison.md)
- [贡献指南](CONTRIBUTING.md)
- 许可证：MIT（见 [LICENSE](LICENSE)）
