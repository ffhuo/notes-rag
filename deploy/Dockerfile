# deploy/Dockerfile — notes-rag 镜像（多阶段：先构建前端，再装 Python，单进程同托管 API + 静态）
# 用法：docker build -f deploy/Dockerfile -t notes-rag .
# 说明：前端（frontend/）在 Stage 1 用 node 构建产物输出到 app/static，
#       Stage 2 复制到镜像内 /app/app/static，由 FastAPI 直接托管，对外只暴露一个端口、同源免 CORS。

# ===== Stage 1：构建前端 =====
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
# vite 的 outDir 为 ../app/static（见 frontend/vite.config.js），
# 在 WORKDIR=/frontend 下即容器内 /app/static —— Stage 2 按此路径复制
RUN npm run build

# ===== Stage 2：Python 运行环境 =====
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

# 安装 uv（极速包管理）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 先复制依赖清单，利用层缓存（uv.lock 已提交则同步锁定版本；--no-dev 排除开发依赖组）
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --python 3.12 --no-dev

# 复制源码 + 前端构建产物
COPY . .
COPY --from=frontend /app/static ./app/static

# 数据持久化建议挂卷到 /app/data（Chroma + SQLite + uploads）
EXPOSE 8000

# 监听地址由环境变量 HOST 控制（本地 127.0.0.1；部署 0.0.0.0）
# 生产务必前置于反向代理 + HTTPS（见 deploy/nginx.conf.example、docs/design.md §15.4 / §17.6）
# 直接调用 venv 内 uvicorn：避免运行时再经 uv 解析环境（无网环境更稳）
CMD ["sh", "-c", "/app/.venv/bin/uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
