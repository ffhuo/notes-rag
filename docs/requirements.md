# 需求清单与范围边界 — rag-as-api

> 本文定义「做什么 / 不做什么 / 做到什么程度算完」，作为练手时的边界锚点。
> 配合 [开发方案设计](design.md) 一起看。

## 1. 项目目标

把 Obsidian vault 里的 Markdown 笔记变成**可检索、可问答**的后端服务（RAG-as-API），
对外提供 REST 接口，自己日常使用（写代码卡壳时直接问「我之前关于 X 的笔记怎么写的」），
同时作为 **FastAPI + AI 集成** 的练手项目。

验收视角：部署在本地、`uv sync`（含 `uv run`）后填 Key 即跑；能用自然语言查到自己笔记里的内容。

## 2. 功能需求（FR）

| 编号 | 功能 | 说明 |
|------|------|------|
| FR1 | 笔记摄取 Ingest | 扫描指定 vault 目录下的 `.md` 文件，解析→分块→生成 embedding→写入向量库，并把元数据落 SQLite。支持全量重建与增量更新（按 mtime）。 |
| FR2 | 语义检索 Search | 给定 query，返回 Top-K 相似片段，含来源文件路径、标题、相似度分数、片段内容。 |
| FR3 | 检索增强问答 Chat | 给定 query + 可选历史，先做语义检索，再把结果拼入 Prompt 交给 LLM，**流式**返回答案，并回传引用来源；记录对话历史。 |
| FR4 | 鉴权 | 受保护接口用 API Key（Header）保护；本地单用户场景足够。JWT 为进阶可选项。 |
| FR5 | 配置 | 通过 `.env` 管理 LLM base_url / api_key / model、vault 路径、向量库与 DB 路径、服务端口、CORS。 |
| FR6 | 健康检查 | `GET /healthz` 探活，供本地监控 / 部署探针使用。 |

## 3. 非功能需求（NFR）

- **NFR1 本地可运行**：SQLite + 本地 Chroma，零外部服务；`uv sync` 后填 Key 即跑。
- **NFR2 异步**：FastAPI 异步接口；embedding / LLM 调用走 async；ingest 可用后台任务。
- **NFR3 类型安全**：Pydantic v2 做请求/响应校验与配置校验。
- **NFR4 可观测**：结构化日志；ingest / chat 有耗时与 token 统计，便于定位慢点。
- **NFR5 易测试**：分层清晰，service / repository 可单测；LLM 与 embedding 可 mock。

## 4. 范围边界与路线

> 本项目**开源、不预设使用边界**。下列「v0.1 起步范围」只是务实的第一版切片，
> 并非永久限制；所有后续能力都已在架构层预留扩展点，欢迎社区贡献。

### v0.1 起步范围（务实切片，非封闭）
- 默认单 vault、单用户、API Key 鉴权（最简可用路径）。
- 纯文本 Markdown 解析：保留原始文本，图片/附件/双链渲染暂不做。
- Chroma 本地持久化向量库。
- 端点：`/ingest`、`/search`、`/chat`（SSE 流式）、`/healthz`。
- SQLite 存笔记元数据 + 对话历史。
- 架构预留：多 vault / 多用户 / 多向量库 / 多 LLM 提供方均可通过配置与数据模型扩展（见 design.md §6、§8、§13）。

### 🗺️ 路线图（Roadmap · 将逐步实现，欢迎 PR）
- 多用户 / 多租户、注册登录、细粒度权限（数据模型已预留 `user_id` / `vault_id` 列）。
- 笔记实时监听（watchdog 文件变更自动重建）。
- 重排（reranker）/ 混合检索（BM25 + 向量）/ 元数据过滤。
- 官方前端（也可由社区提供）。
- Docker / docker-compose / 云部署（K8s Helm 等）。
- 评测集与自动评测、可观测性面板（Prometheus / Grafana）。
- 更多向量库后端（pgvector / Qdrant / Milvus）与更多 LLM 提供方。

## 5. 验收标准（Definition of Done）

- [ ] `uv sync` 后，配置 `.env`，能 `uv run python -m app.main` 启动。
- [ ] `POST /api/v1/ingest` 扫描 vault，进度可见，元数据入库、向量可查。
- [ ] `POST /api/v1/search` 返回相关片段。
- [ ] `POST /api/v1/chat` 流式返回**基于笔记**的答案，且答案引用来源。
- [ ] 未带 API Key 访问受保护接口返回 `401`。
- [ ] 核心 service / repository 有单测（mock LLM 与 embedding）。
- [ ] `http://127.0.0.1:8000/docs` 可看自动生成的接口文档。

## 6. 技术约束

- Python **3.12+**（本机 3.12）。
- FastAPI + Pydantic v2 + Uvicorn。
- SQLite（aiosqlite 异步）或同步 SQLite + 线程池；鼓励 async。
- Chroma（chromadb）本地持久化。
- LLM / Embedding 走 OpenAI 兼容 SDK（`openai` 包），`base_url` 可指向 Qwen / 兼容端点。
- 本机命令统一用 `python`（非 `python3`）。
