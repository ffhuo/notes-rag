# 贡献指南 — notes-rag

欢迎参与本项目！无论是修复 bug、新增检索策略、接入新的向量库，还是补充文档与部署模板，都欢迎提 PR。

## 开发流程

1. Fork 本仓库并 `git clone` 到本地。
2. 用 [uv](https://github.com/astral-sh/uv) 安装依赖：`uv sync --python 3.12`。
3. 复制配置：`cp .env.example .env`（按需调整 `API_KEY` / 摄取过滤等）。**模型配置不在 `.env`**：启动后到前端「模型」页添加 LLM / Embedding 配置（端点见 `docs/design.md` §6 接口总览）。
4. 按 `docs/design.md` 的 Phase 0 → Phase 4 实现或扩展功能。
5. 本地验证：`make test` 跑单测；`make dev` 起服务后用 `make ingest` 验证。
6. 提交前确保：`make test` 通过，新增逻辑有对应测试或文档说明。

## 代码约定

- 遵循分层架构：`api`（路由）→ `services`（业务）→ `repositories` / `rag`（数据 / 管线）→ `core` / `models`（横切 / 模型）。
- 路由层不写业务逻辑；service 不碰 HTTP；依赖通过 FastAPI `Depends` 注入。
- 类型安全：Pydantic v2 校验请求 / 响应与配置。

## 可扩展方向（欢迎认领）

- 多用户 / 多租户、鉴权升级（JWT / OAuth）
- 多 vault、实时监听（watchdog）
- 重排 / 混合检索（BM25 + 向量）、元数据过滤
- 更多向量库后端（pgvector / Qdrant / Milvus）
- 前端（Vue / React）、部署模板（Docker / compose / Helm）

## 提交规范

- 提交信息清晰描述「做了什么 / 为什么」。
- 一个 PR 聚焦一件事，便于 review。
- 重大设计变更请先开 Issue 讨论，或更新 `docs/design.md`。

## 行为准则

请友善、尊重地交流，共同维护开放协作的氛围。
