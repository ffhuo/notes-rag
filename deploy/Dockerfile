# deploy/Dockerfile — notes-rag 镜像（多阶段：先构建前端，再装 Python，单进程同托管 API + 静态）
# 用法：docker build -f deploy/Dockerfile -t notes-rag .
# 说明：前端（frontend/）在 Stage 1 用 node 构建到 frontend/dist，
#       Stage 2 复制到 /app/static，由 FastAPI 直接托管，对外只暴露一个端口、同源免 CORS。

# ===== Stage 1：构建前端 =====
FROM node:20-alpine AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ===== Stage 2：Python 运行环境 =====
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

# 安装 uv（极速包管理）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 先复制依赖清单，利用层缓存（uv.lock 已提交则同步锁定版本）
COPY pyproject.toml uv.lock* ./
RUN uv sync --python 3.12

# 复制源码 + 前端构建产物
COPY . .
COPY --from=frontend /frontend/dist ./app/static

# 数据持久化建议挂卷到 /app/data（Chroma + SQLite + uploads）
EXPOSE 8000

# 监听地址由环境变量 HOST 控制（本地 127.0.0.1；部署 0.0.0.0）
# 生产务必前置于反向代理 + HTTPS（见 deploy/nginx.conf.example、docs/design.md §15.4 / §17.6）
CMD ["sh", "-c", "uv run uvicorn app.main:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
