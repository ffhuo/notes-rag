# Python 基础库选型对比（log / config / database）

> 目的：为 `rag-as-api` 这类「FastAPI + 个人日常使用」的 Python 服务端项目，筛选三个最基础方向（日志、配置、数据库）的高热度库，做横向对比并给出可抄的使用示例。
> 调研时间：2026-09。所有库均为当前 PyPI 上的主流/活跃项目，非冷门。

## 0. 项目现状（对齐用）

当前 `pyproject.toml` 已经安装的、与本文相关的依赖：

| 方向 | 已装 | 状态 |
|------|------|------|
| 配置 | `pydantic-settings>=2.2`、`python-dotenv>=1.0` | ✅ 已定 |
| 数据库 | `sqlalchemy>=2.0`、`aiosqlite>=0.19` | ✅ 已定（异步 SQLite） |
| 日志 | 仅标准库 `logging`（无第三方包） | 🔶 待增强（见 §1.4 推荐） |

> 也就是说，config 和 database 的选型已经落定，本文重点是**把选型理由和使用范式固定下来**，并给 logging 一个建议。

---

## 1. 日志（Logging）

### 1.1 候选库对比

| 维度 | stdlib + python-json-logger | Loguru | structlog |
|------|------|--------|-----------|
| 热度 | 事实标准，所有框架原生支持 | GitHub ~20k★，个人项目极流行 | 结构化日志主流，微服务/可观测首选 |
| 依赖 | 仅加 `python-json-logger` | 单包零依赖 | 单包（可选 `orjson` 加速） |
| 结构化 JSON | 需配 formatter | `serialize=True` 一行搞定 | 原生核心能力（`JSONRenderer`） |
| 文件轮转/压缩 | `RotatingFileHandler`（手动） | 内置 `rotation=`/`compression=` | 委托给 stdlib handler |
| 上下文传播 | `LoggerAdapter`（手动） | `logger.bind()` | `contextvars` 自动跨协程 |
| 异步安全 | 是 | `enqueue=True` 线程安全 | 是（contextvars 正确） |
| OTel 集成 | LoggingHandler 直挂 root | 需经 InterceptHandler 中转 | 原生支持 |
| 学习曲线 | 高（dictConfig 样板多） | 低（两三行） | 中（processor 链概念） |
| 适合 | 库/需要零依赖的场景 | 新应用、追求极简 DX | 微服务、高吞吐、需脱敏/采样 |

### 1.2 一句话定位

- **stdlib + python-json-logger**：最通用、最不会踩坑。所有第三方库都通过它输出，OTel 直接挂 root logger。缺点是要写 `dictConfig` 样板。
- **Loguru**：开发体验天花板。一个 `add()` 配置完轮转/压缩/JSON/异常回溯，单全局 logger 上手极快。代价是没有「按组件分 logger」的层级控制。
- **structlog**：结构化专家。processor 链可组合脱敏、注入 trace_id、采样；`contextvars` 让每一条请求日志自动带 `request_id`，在 asyncio 下零额外配置。可把 stdlib 当输出后端，平滑迁移。

### 1.3 使用示例

**A. stdlib + python-json-logger（零心智负担，最稳）**

```python
# app/core/logging_std.py
import logging
import logging.config
from pythonjsonlogger import jsonlogger

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": jsonlogger.JsonFormatter,
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
    },
    "root": {"level": "INFO", "handlers": ["console"]},
})

log = logging.getLogger("rag")          # 命名 logger，天然支持层级
log.info("ingest started", extra={"vault": "/path/to/vault"})
```

**B. Loguru（极简单应用首选，本项目推荐）**

```python
# app/core/logging_loguru.py
from loguru import logger

# 控制台 JSON + 文件轮转压缩 + 异常回溯
logger.add("data/logs/app.log", rotation="10 MB", retention="7 days",
           compression="zip", serialize=True, enqueue=True, level="INFO")
logger.add("data/logs/error.log", level="ERROR", backtrace=True, diagnose=True)

# 上下文绑定（取代 LoggerAdapter）
req_log = logger.bind(request_id="req-abc", user_id=42)
req_log.info("request received")
req_log.warning("rate limit approaching", remaining=5)

# 捕获第三方库日志（把标准库日志桥接到 loguru）
import logging, sys
class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        logger.opt(depth=6, exception=record.exc_info).log(record.levelno, record.getMessage())
logging.basicConfig(handlers=[InterceptHandler()], level=0)
```

**C. structlog（微服务/可观测/脱敏场景）**

```python
# app/core/logging_struct.py
import logging, structlog
from structlog.contextvars import merge_contextvars, bind_contextvars

structlog.configure(
    processors=[
        merge_contextvars,                 # 自动合并每请求的 contextvars
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
log = structlog.get_logger()

# 在 FastAPI 中间件里绑定 request_id，全链路自动带上
bind_contextvars(request_id="req-abc", method="POST", path="/chat")
log.info("request handled", user_id=42)   # 输出自带 request_id/method/path
```

### 1.4 推荐结论

- **本项目（个人 FastAPI 服务）推荐 Loguru**：两行 `add()` 拿到 JSON + 轮转 + 异常回溯，日常调试体验最好，集成进 `app/core/logging.py` 即可。
- 若以后做**多用户/平台级服务**并接 OTel，再切 structlog；纯练手阶段用 Loguru 性价比最高。
- stdlib 始终可作兜底，不想加依赖时直接用。

---

## 2. 配置（Config）

### 2.1 候选库对比

| 维度 | pydantic-settings | Dynaconf | python-dotenv |
|------|------|---------|---------------|
| GitHub ★ | 属 pydantic 生态（pydantic 主库 20k+★） | ~4.3k★ | ~5k★（.env 加载事实标准） |
| 类型安全 | ✅ 完整 Pydantic 校验 | ⚠️ 部分（type cast + 校验钩子） | ❌ 仅加载字符串 |
| 校验 | ✅ 自动 + 自定义 validator | ✅ 自定义校验器 | ❌ 手动 |
| 配置源 | `.env`、环境变量、secrets | `.env/.toml/.yaml/.json/.ini`、Redis、Vault | 仅 `.env` |
| 嵌套模型 | ✅（`BaseModel` 子模型） | ✅（点号 key） | ❌ |
| Secret 处理 | ✅ `SecretStr`（repr 脱敏） | 插件 | ❌ |
| 多环境 | `env_file` 多文件覆盖 | 原生 `environments` | ❌ |
| 学习曲线 | 中 | 高 | 低 |
| 适合 | Web API / 微服务 | 复杂企业多源配置 | 脚本/小项目（building block） |

### 2.2 一句话定位

- **pydantic-settings**：类型安全配置的事实选择。项目只要用了 Pydantic（FastAPI 必然用），配置模型写法就和 schema 一致；启动即校验、`SecretStr` 防泄露，DX 和生态最佳。**（本项目已用）**
- **Dynaconf**：配置管理的瑞士军刀，支持一堆文件格式 + Vault/Redis 远程源 + 多环境层级。复杂 DevOps 场景才需要，个人项目偏重。
- **python-dotenv**：只干一件事——把 `.env` 读进环境变量。本身不做校验，**它就是 pydantic-settings 的底层依赖**：pydantic-settings 自己并不会直接读 `.env` 文件，而是靠 python-dotenv 先把 `.env` 注入 `os.environ`，它再从环境变量取值。**本项目在 `pyproject.toml` 里把它显式声明只是为了锁定版本**（即便不写，也会随 pydantic-settings 自动安装，属于传递依赖）。**

### 2.3 使用示例

**A. pydantic-settings（本项目已用，推荐）**

```python
# app/core/config.py
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="APP_",          # 读 APP_LLM_API_KEY 而非 LLM_API_KEY
        case_sensitive=False,
    )
    # 必填（缺省启动即报错，fail fast）
    llm_api_key: SecretStr
    # 选填带默认值
    vault_path: str = "./vault"
    chroma_persist_dir: str = "./data/chroma"
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")
    # 嵌套子模型（干净分组）
    class ChromaSettings(BaseSettings):
        host: str = "localhost"
        port: int = 8000
    chroma: ChromaSettings = ChromaSettings()

settings = Settings()                 # 一行实例化即完成加载+校验
print(settings.llm_api_key.get_secret_value())   # 显式取密
```

**B. Dynaconf（多环境/多源时）**

```python
# settings.py
from dynaconf import Dynaconf
settings = Dynaconf(
    settings_files=["settings.toml", ".secrets.toml"],
    environments=True,            # [default] / [production] 分区
    envvar_prefix="APP",
)
print(settings.db.url)             # 嵌套 .toml 自动变属性
```

**C. python-dotenv（仅加载 .env 的底层积木）**

```python
# 一般不用它直接管配置，而是交给 pydantic-settings 底层调用
from dotenv import load_dotenv
import os
load_dotenv()                       # 把 .env 注入 os.environ
API_KEY = os.getenv("API_KEY")     # 之后 pydantic-settings 从这里读
```

### 2.4 推荐结论

- **保持现状：pydantic-settings（python-dotenv 是其底层依赖，自动同装）**。配置即类型化代码，启动即校验，杜绝「运行时才爆配置错误」这一类 bug。python-dotenv 并非独立选型，只是 pydantic-settings 加载 `.env` 的底层工具，无需单独维护；也无需引入 Dynaconf（个人项目用不到其多源/远程能力）。

---

## 3. 数据库（Database）

### 3.1 候选库对比

| 维度 | SQLAlchemy 2.x | SQLModel | Tortoise ORM |
|------|------|---------|--------------|
| GitHub ★ | 企业标准（主库 10k+★） | ~14k★（FastAPI 作者出品） | 社区维护，async 派 |
| 异步 | ✅ `AsyncSession`（原生 async） | ✅（底层即 SQLAlchemy 异步） | ✅ async 原生（asyncpg 驱动） |
| 类型安全 | ✅ 2.x `Mapped[...]` 注解 | ✅⭐⭐⭐⭐⭐（Pydantic 级） | ⭐⭐⭐ |
| 模型即 Schema | ❌ ORM 与 Pydantic 分离 | ✅ 一个模型既是表又是 API schema | ❌ |
| 迁移工具 | Alembic（最成熟） | Alembic（继承 SQLAlchemy） | Aerich（较新） |
| 复杂查询 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐（简单够用） | ⭐⭐⭐ |
| 学习曲线 | 陡 | 低（API 与同步版几乎一致） | 中（Django 风 DSL） |
| 适合 | 复杂业务/长期维护 | FastAPI 快速原型/CRUD | 纯 async 栈 |

### 3.2 一句话定位

- **SQLAlchemy 2.x**：企业级标准，sync/async 双模、复杂 join/批量/连接池调优全有，Alembic 迁移生态最成熟。**（本项目已用）**
- **SQLModel**：FastAPI 作者把 SQLAlchemy 声明式 + Pydantic v2 缝合，一个 `Note` 类既是数据库表又是请求/响应模型，CRUD 几乎零样板。缺点是复杂查询不如裸 SQLAlchemy 灵活。
- **Tortoise ORM**：async 原生、Django 风格 API，纯异步栈下避免线程池开销；生态比 SQLAlchemy 小，迁移用 Aerich。

### 3.3 使用示例

**A. SQLAlchemy 2.x 异步（本项目已用，推荐）**

```python
# app/models/orm.py
from sqlalchemy import String, mapped_column, Mapped
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

class Base(DeclarativeBase): pass

class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(512), unique=True)
    title: Mapped[str] = mapped_column(String(256))

# app/core/database.py
engine = create_async_engine("sqlite+aiosqlite:///./data/app.db", echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)

async def add_note(path: str, title: str) -> None:
    async with Session() as s:
        s.add(Note(path=path, title=title))
        await s.commit()
```

**B. SQLModel（FastAPI 极简范式）**

```python
# 一个模型既是表、又是 API schema
from sqlmodel import SQLModel, Field, create_async_engine, select, Session
from sqlalchemy.ext.asyncio import AsyncSession

class Note(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    path: str = Field(unique=True)
    title: str

engine = create_async_engine("sqlite+aiosqlite:///./data/app.db")

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
```

**C. Tortoise ORM（纯 async 栈）**

```python
from tortoise import Tortoise, fields
from tortoise.models import Model

class Note(Model):
    id = fields.IntField(primary_key=True)
    path = fields.CharField(max_length=512, unique=True)
    title = fields.CharField(max_length=256)

await Tortoise.init(db_url="sqlite://./data/app.db", modules={"models": ["models"]})
await Tortoise.generate_schemas()
```

### 3.4 推荐结论

- **保持现状：SQLAlchemy 2.x + aiosqlite**。为什么没有追更"现代"的 SQLModel？原因有三：
  1. **SQLModel 本质是 SQLAlchemy 的一层封装**，没有脱离 SQLAlchemy 的能力边界——它把 `DeclarativeBase` 的表定义和 Pydantic 的字段校验缝合在一起。选 SQLAlchemy 不会"错过"任何底层特性，只是少了一层糖衣。
  2. **本项目刻意分层**（`models/schemas.py` 的 Pydantic 与 `models/orm.py` 的 SQLAlchemy 分离），而 SQLModel 的最大卖点「一个模型既是数据库表、又是 API 请求/响应 schema」恰恰是**要合并这两者**。在练手学架构、贴近生产的目标下，显式分离 schema 与 orm 更清晰、更利于理解各层职责。
  3. **多表关联 + 长期维护 + 面试**：本项目有对话历史 / 笔记索引等多表关系，后续可能上 Postgres；SQLAlchemy 在复杂 join、relationship 加载策略（`selectinload`/`joinedload`）、bulk 操作、Alembic 迁移和面试考点上都更全更稳。
- 若你**只是想最快出一个 CRUD demo**，SQLModel 确实更省样板（一个类搞定表+API）。但骨架已按 SQLAlchemy 的 `DeclarativeBase` 起好，`design.md` 的 ORM 模型也照此写，切换成本大于收益，维持不动最划算。

---

## 4. 本项目最终选型汇总

| 方向 | 选定 | 备选 | 理由 |
|------|------|------|------|
| 日志 | **Loguru**（建议新增） | stdlib / structlog | 个人 FastAPI 服务，极简 DX + 轮转/JSON 开箱即用 |
| 配置 | **pydantic-settings + python-dotenv** | Dynaconf | 类型安全、启动校验、与 FastAPI 同源，零多余依赖 |
| 数据库 | **SQLAlchemy 2.x + aiosqlite** | SQLModel / Tortoise | 双模+AsyncSession+Alembic，长期维护与面试友好 |

> 想要严格对齐「生产最佳实践」，日志可改为 stdlib + `python-json-logger`；两者都能进 `app/core/logging.py`，不影响其余分层。

## 5. 参考

- Choosing a Python Logging Library in 2026（PyCoder's Weekly）
- Python Configuration Management in 2026（pyrastra.com）
- Python ORMs survey 2026（modelcitizendeveloper.com）
- Self-Hosted Python libraries comparison 2026（pistack.xyz）
