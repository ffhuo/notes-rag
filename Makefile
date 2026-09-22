# Makefile — notes-rag 便捷命令入口
# 用法：make <target>，例如 make install / make dev / make test / make docker-up
# 说明：依赖由 uv 管理（见 README「环境准备（uv）」）。
#       运行前请确保 uv 在 PATH 中（安装方式见 README「环境准备（uv）」）。
#       ⚠ 受限环境（如某些沙箱）下跑 make install 写入 .venv 可能被拦截，
#         需赋予目录写权限后重试。

# 定位 uv：优先用 PATH 中的 uv，否则回退到 pyenv 安装的固定路径
UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.pyenv/versions/3.12.12/bin/uv)

# 默认使用阿里云 PyPI 镜像，覆盖全局 UV_DEFAULT_INDEX（如清华镜像）以避免 403 下载失败。
# 如需换源：make sync UV_INDEX=https://pypi.org/simple
UV_INDEX ?= https://mirrors.aliyun.com/pypi/simple/
# export 后所有 target 的 uv 调用（包括 uv run 的隐式 sync）都会继承此源
export UV_DEFAULT_INDEX = $(UV_INDEX)

# 摄取接口所需的环境变量（运行 make ingest 前请先 export）
API_KEY ?=
VAULT_SOURCES ?=
VAULT_PATH ?=            # 兼容旧字段，等价于 local:<path>
IMAGE ?= notes-rag
TAG ?= latest

.PHONY: help install sync dev run test init-db ingest clean shell \
        frontend-install frontend-dev frontend-build demo \
        frontend-install frontend-dev frontend-build \
        docker-build docker-run docker-up docker-down

help:  ## 显示本帮助
	@echo "notes-rag 可用命令："
	@echo "  make install        安装依赖（uv sync --python 3.12）"
	@echo "  make dev            本地热重载启动（uvicorn，默认 0.0.0.0:8000，便于本机/容器访问）"
	@echo "  make run            直接运行（python -m app.main）"
	@echo "  make test           运行 pytest"
	@echo "  make init-db        初始化 SQLite 表"
	@echo "  make ingest         触发 /ingest 摄取 vault（需先 make dev；API_KEY/VAULT_SOURCES 用环境变量传入）"
	@echo "  make clean          清理运行时数据与 Python 缓存"
	@echo "  make shell          进入 venv 的 python REPL"
	@echo "  make docker-build   构建 Docker 镜像（deploy/Dockerfile）"
	@echo "  make docker-run     运行容器（数据挂 ./data，HOST=0.0.0.0）"
	@echo "  make docker-up      用 docker compose 启动（deploy/docker-compose.yml）"
	@echo "  make docker-down    停止 compose 服务"
	@echo "  make frontend-install  安装前端依赖（cd frontend && npm install）"
	@echo "  make frontend-dev      前端热重载开发（Vite，代理 /api 到 :8000）"
	@echo "  make frontend-build    构建前端到 app/static（由后端托管）"

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

# 摄取需要服务在跑；API_KEY 与 VAULT_SOURCES 通过环境变量传入，例如：
#   export API_KEY=xxx VAULT_SOURCES="local:/path/to/vault,git:https://.../vault.git" && make ingest
ingest:  ## 调用 /api/v1/ingest 摄取 vault
	@if [ -z "$(VAULT_SOURCES)" ] && [ -n "$(VAULT_PATH)" ]; then \
		VAULT_SOURCES="local:$(VAULT_PATH)"; \
	fi; \
	curl -s -X POST http://127.0.0.1:8000/api/v1/ingest \
		-H "X-API-Key: $(API_KEY)" \
		-H "Content-Type: application/json" \
		-d "{\"vault_sources\":[\"$${VAULT_SOURCES}\"],\"rebuild\":false}"

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
