"""配置中心 — 从 .env 读取服务运行所需的全部配置。

能力：
- 用 pydantic-settings 读取环境变量 / .env 文件，类型安全
- 集中管理向量库、数据库、摄取过滤、服务端口等配置项
- 可导出模块级单例，供依赖注入使用

主要类：
- class Settings(BaseSettings): 配置模型
    - 字段：ingest_exts / ingest_exclude_dirs（摄取过滤：扩展名白名单 / 排除目录，详见 §16）
    - 字段：ingest_sync_interval / ingest_sync_on_startup / ingest_settle_seconds /
      ingest_max_concurrency / prune_enabled / prune_ratio_limit / sync_runs_keep /
      progress_flush_ms / watch_enabled / watch_debounce_ms / max_file_size /
      bm25_enabled / vector_recall_* / bm25_recall_* / rerank_candidate_* / retrieval_rrf_k
      （同步与作业：定时触发 / 删除护栏 / 记录裁剪 / 进度节流，见 M03 §8 与 §5.8–§5.13）
    - 字段：chroma_dir / sqlite_path（向量库与 SQLite 持久化路径）
    - 字段：api_key / cors_origins（鉴权与跨域）
    - 字段：host / port（服务监听；本地 127.0.0.1，部署 0.0.0.0）
    - 字段：public_base_url（部署在反向代理后的对外基址，用于生成资源 URL）
    - 字段：enable_multiuser / jwt_secret / upload_dir / ui_enabled（多用户与前端，见 §17）
- settings: Settings —— 可选模块级单例

注意：vault 来源和多模型配置不放在 .env 中，运行时以数据库为唯一真相源
（vaults 表 / model_profiles 表），前端 / API 管理。

关联方案：docs/design.md §2（目录结构与职责）、§8（配置与安全）、§15（部署方案）。
"""

from typing import Annotated, Any, List

import json
import tomllib
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# 列表字段统一走「逗号分隔 或 JSON 数组」两种写法（见下方 _parse_list_field 说明）
StrList = Annotated[List[str], NoDecode]


def _resolve_version() -> str:
    """项目版本号：以 pyproject.toml 为唯一真相源。

    为什么不用 importlib.metadata：本项目 [tool.uv] package = false，不会被安装成包，
    元数据里查不到自身版本。构建产物（wheel / 单文件）中若没有 pyproject.toml，
    由 APP_VERSION 环境变量兜底（见 version 字段的 validation_alias）。

    路径按 __file__ 推导，与启动时的工作目录无关。
    """
    root = Path(__file__).resolve().parents[2]   # app/core/config.py → 项目根
    try:
        with (root / "pyproject.toml").open("rb") as fp:
            return str(tomllib.load(fp)["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "0.0.0+unknown"


class Settings(BaseSettings):
    # ===== 环境变量配置 =====
    DEBUG: bool = False
    # 产品版本号：FastAPI / MCP 的 server version 与前端侧栏展示共用这一处。
    # 真相源是 pyproject.toml；无源码产物（wheel / 单文件）用 APP_VERSION 覆盖。
    # 显式指定 validation_alias，避免 .env 里残留的 VERSION 再次覆盖代码里的版本。
    version: str = Field(default_factory=_resolve_version, validation_alias="APP_VERSION")

    # ===== 摄取过滤（多格式 / 文件夹过滤，见 docs/design.md §16）=====
    # Word(.docx) / PDF / Excel(.xlsx) 均为主依赖，默认启用（.xlsm 可按需显式加入）
    ingest_exts: StrList = ["md", "txt", "docx", "pdf", "xlsx"]
    # 默认排除目录：避免构建产物 / 版本控制 / 应用配置 / 缓存等无关目录灌库
    ingest_exclude_dirs: StrList = [
        "node_modules", ".git", ".obsidian", ".trash", "__pycache__", ".venv",
    ]
    # 单文件字节上限（过滤第 5 步 + 变更判据）；请求级 IngestFilters.max_file_size 可覆盖
    max_file_size: int = 10 * 1024 * 1024

    # ===== 图片处理（多模态索引，见 docs/design.md 图片方案）=====
    # 是否处理图片不由开关决定：仅当解析到的 LLM 配置 params.multimodal 为真时才处理。
    # 以下四个阈值仅约束**本地图片**（远程 http/https 外链直接原样交给模型，不下载、不校验）。
    image_min_width: int = 200        # 本地图最小宽度（px），小于则忽略
    image_min_height: int = 200       # 本地图最小高度（px），小于则忽略
    image_max_bytes: int = 5 * 1024 * 1024   # 单张本地图字节上限，超过则忽略
    image_max_per_doc: int = 20       # 单文档最多处理的图片数，超出部分忽略

    # ===== 同步与作业（变更管理，见 M03 §8 与 §5.8–§5.13）=====
    # 定时同步：0 = 关闭；>0 为间隔秒数（如 300 = 每 5 分钟对全部 vault 提交增量作业）
    ingest_sync_interval: int = 0
    # 启动后是否补一次增量同步（进程重启期间磁盘上的变更靠它收敛）
    ingest_sync_on_startup: bool = False
    # 跳过「刚被写入」的文件：避免索引到写了一半的内容（Obsidian 保存 = 写临时文件 + rename）
    ingest_settle_seconds: int = 2
    # 全局同时进行的 ingest / rebuild 作业数上限（一期 1：嵌入是瓶颈，并发只会互相挤）
    ingest_max_concurrency: int = 1
    # 删除总开关：关 = 只增不删（把 vault 当只读镜像）
    prune_enabled: bool = True
    # 删除护栏 3 的比例阈值：本轮拟删数 / 已知笔记数 超此值 → 拒绝，需 force=true 确认（ADR-7）
    prune_ratio_limit: float = 0.5
    # 每 vault 保留的作业记录条数（超限按时间裁剪；**不裁 queued / running 行**）
    sync_runs_keep: int = 50
    # 进度落库的最小间隔（M03 ADR-13）；阶段跳变与终态强制写，不受此限
    progress_flush_ms: int = 500
    # 文件系统监听（二期；仅 source_type=local 且非网络挂载时生效）
    watch_enabled: bool = False
    watch_debounce_ms: int = 1000      # 事件静默窗口：窗口内事件合并为一次作业提交
    # 混合检索：每类召回及精排候选数均按 top_k 自动扩充并限制上下界
    bm25_enabled: bool = True
    vector_recall_multiplier: int = Field(default=4, ge=1)
    vector_recall_min: int = Field(default=20, ge=1)
    vector_recall_max: int = Field(default=100, ge=1)
    bm25_recall_multiplier: int = Field(default=4, ge=1)
    bm25_recall_min: int = Field(default=20, ge=1)
    bm25_recall_max: int = Field(default=100, ge=1)
    rerank_candidate_multiplier: int = Field(default=4, ge=1)
    rerank_candidate_min: int = Field(default=20, ge=1)
    rerank_candidate_max: int = Field(default=100, ge=1)
    retrieval_rrf_k: int = Field(default=60, ge=1)

    # ===== 存储 =====
    chroma_dir: str = "./data/chroma"
    sqlite_path: str = "./data/rag.db"

    # ===== 服务 =====
    api_key: str = ""
    cors_origins: str = "*"
    host: str = "127.0.0.1"      # 本地 127.0.0.1；Docker/部署 0.0.0.0
    port: int = 8000
    public_base_url: str = ""     # 反向代理后的对外基址（如 https://rag.example.com）

    # ===== 多用户与前端（见 docs/design.md §17）=====
    # 默认关闭（个人单用户），所有资源归合成 owner user_id="default"，接口用 X-API-Key 鉴权；
    # 开启后启用 users 表 + JWT（POST /api/v1/auth/login 签发），jwt_secret 必填。
    enable_multiuser: bool = False
    jwt_secret: str = ""          # 多用户模式必填；用于签发/校验 JWT
    upload_dir: str = "./data/uploads"   # 上传 vault 的解压目录
    ui_enabled: bool = True       # 是否挂载 app/static 前端（Vue SPA，见 §17.1）

    # ===== 日志 =====
    log_level: str = Field(default="INFO", pattern=r"^(INFO|DEBUG|WARNING|ERROR|CRITICAL)$")
    log_file: str = "logs/app.log"
    log_rotation: str = "10 MB"
    log_retention: str = "7 days"
    log_error_file: str = "logs/error.log"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_retrieval_candidate_ranges(self) -> "Settings":
        for prefix in ("vector_recall", "bm25_recall", "rerank_candidate"):
            minimum = getattr(self, f"{prefix}_min")
            maximum = getattr(self, f"{prefix}_max")
            if minimum > maximum:
                raise ValueError(f"{prefix}_min must not exceed {prefix}_max")
        return self

    # ===== 列表字段兼容解析 =====
    # pydantic-settings 对 List[str] 默认按 JSON 解析，写 INGEST_EXTS="a,b" 会直接
    # SettingsError 崩溃。这里放宽为「逗号分隔 或 JSON 数组」两种写法都支持，
    # 与 .env.example 注释保持一致。
    @field_validator("ingest_exts", "ingest_exclude_dirs", mode="before")
    @classmethod
    def _parse_list_field(cls, v: Any) -> Any:
        if v is None or isinstance(v, (list, tuple)):
            return list(v) if isinstance(v, tuple) else v
        if not isinstance(v, str):
            return v
        s = v.strip()
        if not s:
            return []
        if s.startswith("["):            # JSON 数组写法
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass
        return [x.strip() for x in s.split(",") if x.strip()]   # 逗号分隔写法

    def get_cors_origins(self) -> List[str]:
        """获取CORS源列表"""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


settings = Settings()  # 如需模块级单例在此实例化（注意 import 顺序）
