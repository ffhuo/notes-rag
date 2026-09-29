# Makefile — notes-rag 便捷命令入口
# 用法：make <target>，例如 make install / make dev / make test / make docker-up
# 说明：依赖由 uv 管理（见 README「环境准备（uv）」）。
#       运行前请确保 uv 在 PATH 中（安装方式见 README「环境准备（uv）」）。
#       ⚠ 受限环境（如某些沙箱）下跑 make install 写入 .venv 可能被拦截，
#         需赋予目录写权限后重试。

# 定位 uv：优先用 PATH 中的 uv，否则回退到 pyenv 安装的固定路径
UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.pyenv/versions/3.12.12/bin/uv)

# 依赖默认走官方 PyPI；国内网络可指定镜像：make sync UV_INDEX=https://mirrors.aliyun.com/pypi/simple/
# UV_INDEX 非空时才注入 UV_DEFAULT_INDEX，此后所有 target 的 uv 调用（含 uv run 的隐式 sync）都继承此源
UV_INDEX ?=

ifneq ($(UV_INDEX),)
export UV_DEFAULT_INDEX = $(UV_INDEX)
endif

# make ingest 的传参变量（拼进 API 请求体，非应用配置项；vault 配置见 .env.example 说明）
IMAGE ?= notes-rag
TAG ?= latest

.PHONY: help install sync dev run test init-db ingest clean shell \
        frontend-install frontend-dev frontend-build frontend-check frontend-tokens demo \
        frontend-install frontend-dev frontend-build \
        docker-build docker-run docker-up docker-down

help:  ## 显示本帮助
	@echo "notes-rag 可用命令："
	@echo "  make install        安装依赖（uv sync --python 3.12）"
	@echo "  make dev            本地热重载启动（uvicorn，默认 0.0.0.0:8000，便于本机/容器访问）"
	@echo "  make run            直接运行（python -m app.main）"
	@echo "  make test           运行 pytest"
	@echo "  make init-db        初始化 SQLite 表"
	@echo "  make clean          清理运行时数据与 Python 缓存"
	@echo "  make shell          进入 venv 的 python REPL"
	@echo "  make docker-build   构建 Docker 镜像（deploy/Dockerfile）"
	@echo "  make docker-run     运行容器（数据挂 ./data，HOST=0.0.0.0）"
	@echo "  make docker-up      用 docker compose 启动（deploy/docker-compose.yml）"
	@echo "  make docker-down    停止 compose 服务"
	@echo "  make frontend-install  安装前端依赖（cd frontend && npm install）"
	@echo "  make frontend-dev      前端热重载开发（Vite，代理 /api 到 :8000）"
	@echo "  make frontend-build    构建前端到 app/static（由后端托管）"
	@echo "  make frontend-check    前端门禁：构建 + 令牌对比度 + 样式合规（CI 用）"
	@echo "  make frontend-tokens   导出令牌给小程序（rpx）与 RN（TS）"

install:  ## 安装依赖并创建 .venv
	$(UV) sync --python 3.12

sync: install  ## 同 install

dev:  ## 热重载启动开发服务器
	$(UV) run python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run:  ## 直接运行（无热重载）
	$(UV) run python -m app.main

test:  ## 运行测试
	$(UV) run pytest -q

init-db:  ## 初始化数据库表（scripts/init_db.py）
	$(UV) run python scripts/init_db.py

clean:  ## 清理运行时数据与 Python 缓存
	rm -rf data/chroma data/*.db data/*.sqlite data/*.sqlite3
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

shell:  ## 进入 venv 的 python REPL
	$(UV) run python

# ===== 前端（Vue 3 + Vite，详见 docs/design.md §17.1 / §17.6）=====
demo:  ## 打开全模块交互 Demo（demo/index.html，零依赖原型）
	@open demo/index.html 2>/dev/null || echo "请手动打开 demo/index.html"

frontend-install:  ## 安装前端依赖
	cd frontend && npm install

frontend-dev:  ## 前端热重载开发（Vite dev，代理 /api 到后端 :8000）
	cd frontend && npm run dev

frontend-build:  ## 构建前端到 app/static（由后端 FastAPI 托管）
	cd frontend && npm run build

frontend-check:  ## 前端门禁：构建 + 令牌对比度 + 样式合规（CI 用）
	cd frontend && npm run build
	cd frontend && node scripts/check-contrast.mjs
	cd frontend && node scripts/check-style.mjs

frontend-tokens:  ## 导出令牌给小程序（rpx）与 RN（TS），产物在 frontend/tokens/
	cd frontend && node scripts/export-tokens.mjs

# ===== Docker 部署（详见 docs/design.md §15）=====
docker-build:  ## 构建 Docker 镜像
	docker build -f deploy/Dockerfile -t $(IMAGE):$(TAG) .

docker-run:  ## 运行容器（数据持久化到 ./data，监听 0.0.0.0）
	docker run -d --name $(IMAGE) \
		-p 8000:8000 \
		-v $(CURDIR)/data:/app/data \
		--env-file .env \
		-e HOST=0.0.0.0 \
		$(IMAGE):$(TAG)

docker-up:  ## 用 docker compose 启动（含数据卷）
	docker compose -f deploy/docker-compose.yml up -d --build

docker-down:  ## 停止 compose 服务
	docker compose -f deploy/docker-compose.yml down
