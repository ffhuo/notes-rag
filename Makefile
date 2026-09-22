# Makefile — rag-as-api 便捷命令入口
# 用法：make <target>，例如 make install / make dev / make test
# 说明：依赖由 uv 管理（见 README「环境准备（uv）」）。
#       运行前请确保 uv 在 PATH 中（安装方式见 README「环境准备（uv）」）。
#       ⚠ 受限环境（如某些沙箱）下跑 make install 写入 .venv 可能被拦截，
#         需赋予目录写权限后重试。

# 定位 uv：优先用 PATH 中的 uv，否则回退到 pyenv 安装的固定路径
UV := $(shell command -v uv 2>/dev/null || echo $(HOME)/.pyenv/versions/3.12.12/bin/uv)

# 摄取接口所需的环境变量（运行 make ingest 前请先 export）
API_KEY ?=
VAULT_PATH ?=

.PHONY: help install sync dev run test init-db ingest clean shell

help:  ## 显示本帮助
	@echo "rag-as-api 可用命令："
	@echo "  make install    安装依赖（uv sync --python 3.12）"
	@echo "  make dev        本地热重载启动（uvicorn --reload，端口 8000）"
	@echo "  make run        直接运行（python -m app.main）"
	@echo "  make test       运行 pytest"
	@echo "  make init-db    初始化 SQLite 表"
	@echo "  make ingest     触发 /ingest 摄取 vault（需先 make dev；API_KEY/VAULT_PATH 用环境变量传入）"
	@echo "  make clean      清理运行时数据与缓存"
	@echo "  make shell      进入 venv 的 python REPL"

install:  ## 安装依赖并创建 .venv
	$(UV) sync --python 3.12

sync: install  ## 同 install

dev:  ## 热重载启动开发服务器
	$(UV) run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

run:  ## 直接运行（无热重载）
	$(UV) run python -m app.main

test:  ## 运行测试
	$(UV) run pytest -q

init-db:  ## 初始化数据库表（scripts/init_db.py）
	$(UV) run python scripts/init_db.py

# 摄取需要服务在跑；API_KEY 与 VAULT_PATH 通过环境变量传入，例如：
#   export API_KEY=xxx VAULT_PATH=/path/to/vault && make ingest
ingest:  ## 调用 /api/v1/ingest 摄取 vault
	curl -s -X POST http://127.0.0.1:8000/api/v1/ingest \
		-H "X-API-Key: $(API_KEY)" \
		-H "Content-Type: application/json" \
		-d '{"vault_path":"$(VAULT_PATH)","rebuild":false}'

clean:  ## 清理运行时数据与 Python 缓存
	rm -rf data/chroma data/*.db data/*.sqlite data/*.sqlite3
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

shell:  ## 进入 venv 的 python REPL
	$(UV) run python
