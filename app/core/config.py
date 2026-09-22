"""配置中心 — 从 .env 读取服务运行所需的全部配置。

能力：
- 用 pydantic-settings 读取环境变量 / .env 文件，类型安全
- 集中管理 LLM、向量库、数据库、服务端口等配置项
- 可导出模块级单例，供依赖注入使用

主要类：
- class Settings(BaseSettings): 配置模型
    - 字段：llm_base_url / llm_api_key / llm_model（LLM 对话 / 问答）
    - 字段：embed_base_url / embed_api_key / embed_model（Embedding 向量化，可回退 LLM 端点/密钥）
    - 字段：model_profiles（多模型种子；运行时多模型以 model_profiles 表为准，见 §18）
    - 字段：vault_sources（vault 来源列表：本地引用 / 远程导入，详见 docs/design.md §15.3；
            兼容旧字段 vault_path 单 vault 本地路径）
    - 字段：ingest_exts / ingest_exclude_dirs（摄取过滤：扩展名白名单 / 排除目录，详见 §16）
    - 字段：chroma_dir / sqlite_path（向量库与 SQLite 持久化路径）
    - 字段：api_key / cors_origins（鉴权与跨域）
    - 字段：host / port（服务监听；本地 127.0.0.1，部署 0.0.0.0）
    - 字段：public_base_url（部署在反向代理后的对外基址，用于生成资源 URL）
    - 字段：enable_multiuser / jwt_secret / upload_dir / ui_enabled（多用户与前端，见 §17）
- settings: Settings —— 可选模块级单例

关联方案：docs/design.md §2（目录结构与职责）、§8（配置与安全）、§15（部署方案）。
"""

from typing import Annotated, Any, List

import json

from pydantic import Field, SecretStr, field_validator

from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# 列表字段统一走「逗号分隔 或 JSON 数组」两种写法（见下方 _parse_list_field 说明）
StrList = Annotated[List[str], NoDecode]
# JSON 数组字段（元素为对象）：同样禁用 pydantic-settings 的默认解码，交由自定义校验器处理
JsonList = Annotated[List[dict], NoDecode]


class Settings(BaseSettings):
    # ===== 环境变量配置 =====
    DEBUG: bool = False
    version: str = "0.1.0"

    # ===== LLM（对话 / 问答，OpenAI 兼容端点）=====
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr
    llm_model: str = "gpt-4o-mini"

    # ===== Embedding（文本向量化，OpenAI 兼容端点）=====
    # 默认留空，回退到 LLM 同款端点 / 密钥（多数兼容服务两者共用，如 Qwen、本地 vLLM）；
    # 若使用独立 embedding 服务（如本地 BGE-M3、不同供应商），在此显式覆盖即可。
    embed_base_url: str = ""                # 空 = 回退 llm_base_url
    embed_api_key: SecretStr = SecretStr("")  # 空 = 回退 llm_api_key
    embed_model: str = "text-embedding-3-small"

    # ===== vault 来源（本地引用 / 远程导入）=====
    # 多源逗号分隔，每项格式见 docs/design.md §15.3：
    #   local:/abs/path        git:https://.../vault.git
    #   http(s)://.../vault.zip  http(s)://.../notes/
    # 兼容：单 vault 仍可用 VAULT_PATH（等价于 local:<path>），优先读 vault_sources
    vault_sources: StrList = []
    vault_path: str = ""  # 兼容旧字段，等价于 local:<vault_path>

    # ===== 多模型种子（运行时以 model_profiles 表为准，见 docs/design.md §18）=====
    # JSON 数组，每项：{kind, name, model, provider?, base_url?, api_key?, params?, is_default?}
    # 仅用于「表为空时」的一次性注入；前端/API 配好后以库为准
    model_profiles: JsonList = []

    # ===== 摄取过滤（多格式 / 文件夹过滤，见 docs/design.md §16）=====
    # 一期仅 md / txt；PDF / Word / Excel 等随 parser 实现启用（pyproject 可选依赖 docs 组）
    ingest_exts: StrList = ["md", "txt"]
    # 默认排除目录：避免构建产物 / 版本控制 / 应用配置 / 缓存等无关目录灌库
    ingest_exclude_dirs: StrList = [
        "node_modules", ".git", ".obsidian", ".trash", "__pycache__", ".venv",
    ]

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

    # ===== 列表字段兼容解析 =====
    # pydantic-settings 对 List[str] 默认按 JSON 解析，写 VAULT_SOURCES="a,b" 会直接
    # SettingsError 崩溃。这里放宽为「逗号分隔 或 JSON 数组」两种写法都支持，
    # 与 .env.example 注释保持一致。
    @field_validator("vault_sources", "ingest_exts", "ingest_exclude_dirs", "model_profiles", mode="before")
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

    def get_vault_sources(self) -> List[str]:
        """返回生效的 vault 来源列表（vault_sources 优先，否则回退 vault_path）。"""
        if self.vault_sources:
            return list(self.vault_sources)
        if self.vault_path:
            return [f"local:{self.vault_path}"]
        return []

    def get_cors_origins(self) -> List[str]:
        """获取CORS源列表"""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    def get_embed_base_url(self) -> str:
        """Embedding 端点：显式配置优先，否则回退 LLM 端点。"""
        return self.embed_base_url or self.llm_base_url

    def get_embed_api_key(self) -> SecretStr:
        """Embedding 密钥：显式配置优先，否则回退 LLM 密钥。"""
        return self.embed_api_key if self.embed_api_key.get_secret_value() else self.llm_api_key

    def bootstrap_profiles(self) -> List[dict]:
        """返回由 .env 构造的「种子模型配置」（仅用于 model_profiles 表为空时注入，见 §18.4）。

        - 无论哪种情况都会产出一个 llm 与一个 embed 的默认配置（name='default'），
          取值即 LLM_* / EMBED_*（EMBED_* 留空时按回退规则取 LLM_*，与单机用法一致）。
        - MODEL_PROFILES（JSON 数组）里的额外配置追加在后面；若某项声明 is_default=true，
          同 kind 的 'default' 自动让位（一个 kind 只保留一个默认项）。
        """
        seeds: List[dict] = [
            {
                "kind": "llm", "name": "default", "provider": "openai",
                "base_url": self.llm_base_url,
                "api_key": self.llm_api_key.get_secret_value(),
                "model": self.llm_model, "params": {}, "is_default": True,
            },
            {
                "kind": "embed", "name": "default", "provider": "openai",
                "base_url": self.get_embed_base_url(),
                "api_key": self.get_embed_api_key().get_secret_value(),
                "model": self.embed_model, "params": {}, "is_default": True,
            },
        ]
        for raw in self.model_profiles:
            if not isinstance(raw, dict) or not raw.get("name") or not raw.get("kind"):
                continue                                   # 忽略残缺项，避免启动崩溃
            item = {
                "kind": str(raw.get("kind")), "name": str(raw.get("name")),
                "provider": str(raw.get("provider", "openai")),
                "base_url": str(raw.get("base_url", "")),
                "api_key": str(raw.get("api_key", "")),
                "model": str(raw.get("model", "")),
                "params": raw.get("params") or {},
                "is_default": bool(raw.get("is_default", False)),
            }
            if item["is_default"]:
                for s in seeds:
                    if s["kind"] == item["kind"]:
                        s["is_default"] = False
            seeds.append(item)
        return seeds


settings = Settings()  # 如需模块级单例在此实例化（注意 import 顺序）
