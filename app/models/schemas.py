"""Pydantic 模型 — 请求与响应的数据契约（DTO）。

能力：
- 定义 /ingest、/search、/chat 接口的请求体
- 定义检索命中、对话事件等响应体
- 提供类型校验，配合 FastAPI 自动生成 OpenAPI 文档

主要类：
- IngestRequest: { vault_path / vault_sources / vault_id, mode: "sync"|"rebuild", dry_run, prune, force }
- RunSubmitResponse: { run_id, vault_id, status }        # 单库作业提交（202）
- IngestSubmitResponse: { vault_ids, run_ids, skipped }  # /ingest 多源聚合提交（202）
- SyncRunOut / SyncRunDetail: 作业记录与进度（total=None 表示不确定进度）
- SearchRequest: { query: str, top_k: int = 5, threshold: float = 0.0 }
- ChunkHit: { note_id, file_path, title, content, score }  # 单条检索命中
- SearchResponse: { hits: list[ChunkHit] }
- ChatRequest: { query: str, conversation_id: str | None, top_k: int = 5 }
- ChatEvent: { type: "token"|"sources"|"done", ... }  # SSE 事件载荷
- ConversationOut / MessageOut：会话历史出参（列表标题 + 会话内消息）
- TranscribeOut: { text, model, elapsed_ms }  # 语音转文字结果
- ModelRuntime / ModelProfileCreate / ModelProfileUpdate / ModelProfileOut：多模型配置（§18）
  - ModelRuntime 是解析后的运行时配置，rag 层只依赖它，不反向依赖 service / DB
- 变更管理（M03 §5.8–§5.12）：
  - SyncPlan:   对账计划 { adds, updates, moves, deletes, unchanged, blocked_reason, samples }
  - SyncResult: SyncPlan + 实际执行 { failed, failed_files, skipped_reason, elapsed_ms }
  - SyncRunOut: 同步运行记录（前端展示「上次同步做了什么」）
  - DoctorReport: 三向一致性自检 { ghost_vectors, missing_vectors, orphan_notes, model_mismatch }

关联方案：docs/design.md §5（API 设计）、§10（手写 TODO 地图）、§18（多模型管理）。
变更管理（增量同步 / 删除护栏 / 一致性自检）详见设计文档库 M03 §5.8–§5.12。
"""
from typing import Any, List, Literal

from pydantic import BaseModel, SecretStr


class IngestFilters(BaseModel):
    """摄取过滤条件（可选，覆盖配置默认值，见 docs/design.md §16.3）。

    - include: 相对 vault 根的路径 glob 白名单；为空 = 不限
    - exclude: 相对 vault 根的路径 glob 黑名单；优先于 include
    - exts:    扩展名白名单，覆盖 config.ingest_exts
    - max_file_size: 文件字节上限；超过则跳过，None = 不限
    """

    include: List[str] | None = None
    exclude: List[str] | None = None
    exts: List[str] | None = None
    max_file_size: int | None = None


class IngestRequest(BaseModel):
    vault_path: str | None = None           # 兼容单 vault（等价于 local:<path>）
    vault_sources: List[str] | None = None  # CLI/MCP 一次性摄取传多源（不落库为 vault 实体；前端走 vaults + sync）
    vault_id: str | None = None             # 或指定已存在的 vault（前端走 vaults + sync/reindex，见 §17.2）
    # 变更管理（见 M03 §5.8–§5.10）：
    #   mode="sync"    增量对账（新增/修改/删除/改名），日常用这个
    #   mode="rebuild" 全量重建（换 embedding / 改分块参数 / 索引疑似损坏）
    #   注意：换 embedding 只能走 rebuild —— 增量会让同一 collection 混入两种向量空间的向量
    mode: Literal["sync", "rebuild"] = "sync"
    dry_run: bool = False                   # 只算不写，返回 SyncPlan（让用户先看「这次会动什么」）
    prune: bool = True                      # 是否允许删除向外传播；仍受三道护栏约束
    force: bool = False                     # 覆盖「删除比例超阈值」的拦截（用户已确认）
    filters: IngestFilters | None = None    # 文件/文件夹过滤（见 docs/design.md §16）
    # 用哪个 embedding 配置建索引（name 或 id）；留空 = 当前默认 embed profile
    # 注意：换 embedding 会写入新的向量集合，同一 vault 可并存多份索引（见 §18.2）
    embed_profile: str | None = None


class SyncRequest(BaseModel):
    """vault 维度的作业提交体（POST /vaults/{id}/sync 与 /reindex）。

    与 IngestRequest 的分工：`IngestRequest` 面向**源**（CLI/MCP 直接传 vault_path /
    vault_sources，服务端按需 upsert 成 vault 实体）；本模型面向**已存在的 vault 实体**
    —— vault 由 URL 路径给定，故刻意不含 vault_path / vault_sources / vault_id，
    避免「路径里一个 vault、body 里另一个」的两处真相。

    字段语义与 IngestRequest 的同名字段完全一致（见 M03 §5.7 / §5.9 / §5.10）。
    """

    mode: Literal["sync", "rebuild"] = "sync"
    dry_run: bool = False
    prune: bool = True
    force: bool = False
    filters: IngestFilters | None = None
    embed_profile: str | None = None


class RunSubmitResponse(BaseModel):
    """单库作业提交响应（202）：作业已受理。

    语义要点：此时作业**尚未开跑或刚抢到锁**，不代表已成功。
    结果与进度请查 GET /vaults/{id}/runs/{run_id}（M03 §5.13.2）。
    """

    run_id: int
    vault_id: int
    status: Literal["queued", "running"]    # 抢到锁即 running


class IngestSubmitResponse(BaseModel):
    """POST /ingest 的聚合提交响应：多源 = 多作业（M03 §5.7）。

    skipped 里是提交失败 / 被跳过的源（如该 vault 已有作业在跑 →
    reason="already_running" 并带上现有 run_id，便于调用方直接跟进那个任务）。
    """

    vault_ids: List[int] = []
    run_ids: List[int] = []
    skipped: List[dict] = []


# ===== 变更管理：同步计划 / 结果 / 运行记录 / 一致性自检（M03 §5.8–§5.12）=====
class SyncPlan(BaseModel):
    """同步计划：一次对账「打算做什么」。dry_run 时直接返回它，不写任何存储。

    - adds / updates / moves / deletes：四类变更的动作数（moves = 改名/移动，零 embedding）
    - unchanged：未变化的文件数（判据全等，直接跳过）
    - prune_blocked：删除被护栏拦截（见下方 blocked_reason）
    - samples：每类前 10 条**相对路径**，供 UI 展示「具体会动哪些文件」
    """

    vault_id: int
    mode: Literal["sync", "rebuild"]
    adds: int = 0
    updates: int = 0
    moves: int = 0
    deletes: int = 0
    unchanged: int = 0
    prune_blocked: bool = False
    # source_unavailable: 源不可达 → 整个 sync 被中止（绝不当成「内容全没了」）
    # scan_incomplete:   遍历不完整（权限/IO 错误）→ 本轮只增不删
    # over_ratio:        删除比例超阈值 → 需 force=true
    # prune_disabled:    prune=false
    blocked_reason: Literal[
        "source_unavailable", "scan_incomplete", "over_ratio", "prune_disabled"
    ] | None = None
    samples: dict[str, List[str]] = {}


class SyncResult(SyncPlan):
    """同步执行结果：计划字段 + 实际执行情况。

    与 SyncPlan 的差异必须可解释（如执行期文件被删）—— 差异记入 sync_runs.detail_json。
    """

    failed: int = 0
    failed_files: List[dict] = []           # [{path, reason}]，与 sync_runs.detail_json 同源
    skipped_reason: str | None = None       # 如 already_running（同 vault 正在同步，不排队）
    elapsed_ms: int = 0


class SyncRunOut(BaseModel):
    """作业记录（列表出参）：前端 vault 卡片与「任务与进度」列表用（M07 §5.4）。

    - status 七态：queued / running 为进行中；success / partial 为完成；
      failed（程序异常）/ cancelled（用户主动停止）/ aborted（进程崩溃）是三种语义不同的终态
    - total 为 None 表示**该阶段总量不可知**（scan 阶段）→ 前端进度条转「不确定态」
    - cancelling：已收到取消请求但循环尚未到安全点（前端显示「正在停止…」并禁用按钮）
    """

    id: int
    vault_id: int
    trigger: str                            # manual | schedule | watch | startup | cli | mcp
    mode: str                               # sync | rebuild
    dry_run: bool
    status: str
    stage: str | None = None                # probe|scan|diff|plan|plan_ready|index|prune|done
    total: int | None = None
    processed: int = 0
    current_item: str | None = None
    cancelling: bool = False
    adds: int = 0
    updates: int = 0
    moves: int = 0
    deletes: int = 0
    unchanged: int = 0
    failed_cnt: int = 0
    blocked_reason: str | None = None
    error: str | None = None
    started_at: int | None = None           # UTC 毫秒时间戳（前端 new Date(ms) 直接用）
    finished_at: int | None = None          # 同上；未收尾为 None
    elapsed_ms: int = 0


class SyncRunDetail(SyncRunOut):
    """作业详情（进度轮询的唯一出参，M03 §5.13.3）。

    在列表字段之上补 message 与产物载荷：
    - plan：仅 dry_run 作业到达 stage=plan_ready 后可见
    - result：仅执行类作业收尾后可见
    """

    message: str | None = None
    plan: SyncPlan | None = None
    result: SyncResult | None = None


class DoctorReport(BaseModel):
    """三向一致性自检结果（Chroma ↔ chunks ↔ 磁盘）。

    - ghost_vectors：**向量库有、chunks 表无** → 检索会召回已删除内容（最高危）
    - missing_vectors：chunks 表有、向量库无 → 漏召回
    - orphan_notes：notes 有、磁盘无 → 正常中间态，执行一次 sync 即可清理
    - model_mismatch：collection 内维度不一致，或 chunks.embed_profile_id 与 collection 命名不符
    """

    vault_id: int
    ghost_vectors: int = 0
    missing_vectors: int = 0
    orphan_notes: int = 0
    model_mismatch: bool = False
    samples: dict[str, List[str]] = {}


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    threshold: float = 0.0
    vault_id: str | None = None
    # 不提供 embed_profile：检索必须用「建索引时那个」embedding，否则向量空间不兼容（见 §18.2）。
    # 想换 embedding → 先对该 vault 重新 ingest，再检索。


class ChunkHit(BaseModel):
    """检索命中的片段。

    images 来自 chunk.metadata["images"]（ingest 阶段写入），描述**本片段内含**的图片：
    uid（关联 image_cache 行的溯源依据）/ ref（图片地址：URL 或相对 vault 根的路径）/
    kind（local|remote）/ raw（原始图片语法，供回填）/ alt / offset（片段内偏移）/ model。
    无图片段为空列表（pydantic v2 会为每个实例新建 list，不存在共享可变默认值问题）。
    """

    note_id: str
    file_path: str
    title: str
    content: str
    score: float
    images: list[dict] = []


class SearchResponse(BaseModel):
    hits: list[ChunkHit]


class ChatRequest(BaseModel):
    query: str
    conversation_id: str | None = None
    top_k: int = 5
    vault_id: str | None = None
    # 选择用哪个 LLM 配置（name 或 id）；留空 = 当前默认 llm profile。
    # LLM 无状态耦合，可每次请求自由切换（见 §18.2）
    llm_profile: str | None = None


# ===== 对话历史（GET /api/v1/conversations，见 docs/design.md §4.3）=====
class ConversationOut(BaseModel):
    """会话列表项。

    title 是**派生值**：取该会话首条 user 提问压平空白后截断（库里没有 title 列）；
    message_count 为会话内全部消息数（user + assistant）。
    """

    id: int
    title: str
    message_count: int = 0
    created_at: int | None = None    # UTC 毫秒时间戳（前端 new Date(ms) 直接用）


class MessageOut(BaseModel):
    """会话内的一条消息。

    刻意不含 sources：messages 表只存 role/content，引用片段没有落库，
    历史回看时看不到当时引用了哪些笔记（见 M07 §5.5 已知边界）。
    """

    id: int
    role: str
    content: str
    created_at: int | None = None    # UTC 毫秒时间戳


# ===== 语音（POST /api/v1/audio/transcribe）=====
class TranscribeOut(BaseModel):
    """语音转文字结果。

    text 是**识别原文**（未做任何润色）：它会被填进输入框让用户改错字，
    不直接发送 —— 语音识别是概率结果，把错字直接发给检索等于把错误放大。
    """

    text: str
    model: str = ""
    elapsed_ms: int = 0


# ===== 多模型管理（见 docs/design.md §18）=====
class ModelRuntime(BaseModel):
    """解析后的运行时模型配置 —— rag 层（embedder / llm_client）唯一依赖的模型对象。

    由 model_service.to_runtime(profile) 从 ModelProfile 解析得到：
    已带上默认参数，rag 层不再关心 DB、用户默认等概念。
    """

    kind: str                      # llm | embed | asr
    name: str                      # profile 名，便于日志与追踪
    base_url: str
    api_key: SecretStr
    model: str
    params: dict[str, Any] = {}


class ModelProfileCreate(BaseModel):
    """新建一个模型配置（LLM / Embedding / ASR）。"""
    kind: str                                   # llm | embed | asr
    name: str                                   # 用户内唯一，如 'qwen-max' / 'bge-m3-local'
    model: str                                  # 模型标识，如 gpt-4o-mini / text-embedding-3-small
    provider: str = "openai"                    # OpenAI 兼容协议（Qwen / vLLM / 本地服务同）
    base_url: str = ""                          # 留空 = 用 OpenAI 官方端点
    api_key: str = ""                           # 留空 = 不带鉴权（第三方服务通常必填）
    params: dict[str, Any] = {}                 # temperature / dim / max_tokens / timeout …
    set_default: bool = False                   # 是否同时设为该 kind 的默认项


class ModelProfileUpdate(BaseModel):
    """局部更新模型配置；未提供的字段保持不变。"""
    name: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None
    set_default: bool | None = None


class ModelProfileOut(BaseModel):
    """模型配置出参 —— 注意：api_key 永不返回，只给脱敏后的掩码。"""
    id: int
    kind: str
    name: str
    provider: str
    base_url: str
    model: str
    params: dict[str, Any] = {}
    is_default: bool = False
    enabled: bool = True
    origin: str = "ui"                # ui | env
    api_key_masked: str = ""          # 如 'sk-ab****yz'；未配置则为空串


class ModelTestResult(BaseModel):
    """连通性测试结果（POST /models/{id}/test 或 /models/test 试连未保存的配置）。"""
    ok: bool
    model: str
    elapsed_ms: int = 0
    error: str | None = None
    detail: str = ""                  # 例如返回维度（embed）或首块回复（llm）


# ===== Vault（前端配置，见 docs/design.md §17.2）=====
class VaultCreate(BaseModel):
    """新建 vault：本地目录（填 source_value 路径）或上传（source_type=uploaded，文件走 multipart）。"""
    name: str
    source_type: str                       # local / uploaded / git / remote
    source_value: str | None = None        # local→绝对路径；git/remote→URL；uploaded 由文件决定
    filters: "IngestFilters | None" = None  # 该 vault 的摄取过滤（§16.3）


class VaultUpdate(BaseModel):
    """改 vault 配置：**只允许** name 与 filters。

    source_type / source_value 刻意不可改 —— 换源等于换一个库，把已有索引指向
    另一个目录会让「磁盘内容」与「已建索引」无声错配；应新建 vault。

    未出现在请求体里的字段不动（路由用 model_fields_set 判断）；
    filters 显式传 null = 清空该 vault 的过滤（回到 settings 默认）。
    """
    name: str | None = None
    filters: "IngestFilters | None" = None


class VaultBrowseEntry(BaseModel):
    """目录树的一个子目录节点（GET /vaults/browse）。"""
    name: str                              # 目录名（展示用）
    rel: str                               # 相对浏览根的 POSIX 路径，如 notes/private
    has_children: bool = False             # 是否还有下一层（决定是否显示展开箭头）


class VaultBrowseOut(BaseModel):
    """目录树一层的结果（懒加载：前端每次展开只请求一层）。"""
    root: str                              # 被浏览的根目录绝对路径（回显，便于前端确认）
    rel: str = ""                          # 本层相对根的路径；"" = 根目录本身
    entries: List[VaultBrowseEntry] = []


class VaultOut(BaseModel):
    id: int
    user_id: str
    name: str
    source_type: str
    source_value: str
    origin: str = "ui"                     # 一期恒为 "ui"（前端/API 创建；.env 种子已废弃）
    indexed_at: int | None = None          # UTC 毫秒时间戳（未建过索引为 None）
    # 该 vault 的摄取过滤；None = 未设置（用 settings 默认）
    filters: "IngestFilters | None" = None
    # 作业回写状态（见 M06 ADR-9）：只在作业成功后更新，失败/取消保持原值
    embed_profile_id: int | None = None
    embed_indexed_profiles: List[int] = []


# ===== 多用户鉴权（ENABLE_MULTIUSER=true，见 docs/design.md §17.3）=====
class UserCreate(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    uid: str
    username: str
    is_admin: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
