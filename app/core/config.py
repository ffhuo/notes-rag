"""配置中心 — 从 .env 读取服务运行所需的全部配置。

能力：
- 用 pydantic-settings 读取环境变量 / .env 文件，类型安全
- 集中管理 LLM、向量库、数据库、服务端口等配置项
- 可导出模块级单例，供依赖注入使用

主要类：
- class Settings(BaseSettings): 配置模型
    - 字段：llm_base_url / llm_api_key / llm_model / embed_model（LLM 与嵌入）
    - 字段：vault_path（笔记源目录；MVP 单 vault，架构预留多 vault 扩展）
    - 字段：chroma_dir / sqlite_path（向量库与 SQLite 持久化路径）
    - 字段：api_key / cors_origins（鉴权与跨域）
    - 字段：host / port（服务监听）
- settings: Settings —— 可选模块级单例

关联方案：docs/design.md §2（目录结构与职责）、§8（配置与安全）。
"""
from pathlib import Path
from pydantic import Field, SecretStr


from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ===== LLM / Embedding（OpenAI 兼容端点）=====
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr
    llm_model: str = "gpt-4o-mini"
    embed_model: str = "text-embedding-3-small"

    # ===== 数据源 =====
    vault_path: str = ""

    # ===== 存储 =====
    chroma_dir: str = "./data/chroma"
    sqlite_path: str = "./data/rag.db"

    # ===== 服务 =====
    api_key: str = ""
    cors_origins: str = "*"
    host: str = "127.0.0.1"
    port: int = 8000

    # ===== 日志 =====
    log_level: str = Field(default="INFO", pattern=r"^(INFO|DEBUG|WARNING|ERROR|CRITICAL)$")
    log_file: str = "logs/app.log"
    log_rotation: str = "10 MB"
    log_retention: str = "7 days"
    log_error_file: str = "logs/error.log"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # 如需模块级单例在此实例化（注意 import 顺序）
