# Reranker 能力设计

## 状态

设计已确认，尚未实施。本文仅记录方案，不代表功能已经可用。

## 背景与目标

当前检索流程由 `retrieval_service.retrieve` 编排：使用 vault 绑定的 embedding 模型生成查询向量，通过 Chroma 按 cosine similarity 召回 Top-K，并立即组装 `ChunkHit`。Search 和 Chat 共用此检索服务，因此在共享检索编排层增加 rerank 阶段即可让两个入口一致受益。

目标是在不改变现有索引、向量集合和默认检索行为的前提下，为用户提供独立配置的 rerank API。首版支持硅基流动和 Cohere，改善候选片段相关性，并保留第三方服务故障时的可用性。

## 决策

1. **独立 rerank profile**：在现有 `model_profiles` 中新增 `kind=rerank`。沿用用户隔离、默认项、启停、API 地址、密钥和模型名；表结构中的 `kind` 是普通字符串，无需数据库迁移。
2. **默认项控制启用**：有默认 rerank profile 时，Search 与 Chat 自动使用；没有默认项时不调用 reranker，保持现有向量排序。
3. **首版 provider**：使用独立协议适配器分别支持硅基流动与 Cohere。协议标识放在 `params.protocol`，provider 请求/响应差异不进入检索服务。
4. **故障降级**：rerank 超时、HTTP 错误或响应校验失败时，保留原始向量排序结果，继续完成检索；通过结构化 warning 日志记录 profile、provider、失败阶段和错误原因，不静默吞错。
5. **候选数量**：沿用请求的 `top_k` 作为最终返回条数，内部候选数使用 `min(max(top_k * 4, 20), 100)`。首版不新增 UI 或请求参数调节候选数。
6. **分数兼容**：`ChunkHit.score` 继续表示向量相似度；新增可选 `rerank_score` 表示 provider 返回的相关性分数。不得将二者混用或比较。

## 请求流程

```text
Search / Chat
    → retrieval_service.retrieve
    → 使用 vault 绑定的 embedding 生成 query vector
    → Chroma 按当前 threshold 召回候选
    → （存在默认 rerank profile 时）调用对应协议适配器
    → 按 relevance score 排序，截取最终 top_k
    → 构造 ChunkHit，交给 Search 响应或 Chat sources 事件
```

`threshold` 仍只作用于向量召回阶段；rerank 分数与 cosine similarity 标度不同，不能用现有阈值筛选。候选文档使用 chunk 正文及标题信息；正文中已回插的图片描述自然包含在重排文本中。图片元数据、文件来源和其他 Chroma metadata 原样保留。

若 API 返回的候选索引非法、重复或分数无效，应将该次重排视为整体失败并回退原顺序，避免产生部分重排的歧义。对 provider 合法返回的子集，适配器需按协议语义处理；不凭未返回文档推断分数。

## 组件与配置面

- **模型 schemas / API**：允许 `rerank` kind，支持创建、更新、列出、启用/停用、设默认和删除。现有 `kind` 字段为字符串，因此无 ORM schema 迁移。
- **模型管理 UI**：新增 rerank 标签、表单及 provider/protocol 选择；共用现有模型 CRUD 和密钥脱敏流程。
- **Rerank 客户端**：新增隔离的客户端模块，使用异步 HTTP 请求；根据 `params.protocol` 形成硅基流动或 Cohere 请求，解析结果为统一的候选索引与 relevance score。设置合理超时，不复用仅适用于 chat/embedding 的 OpenAI SDK 调用。
- **模型连通性测试**：`/models/test` 和已保存 profile 的 test endpoint 针对 rerank 调用少量固定 query/documents，验证认证、协议和响应格式；错误经现有 `ModelTestResult` 返回。
- **模型解析**：复用用户级默认 profile 机制。仅当存在默认且启用的 rerank profile 才尝试重排；调用方仍可在 Search/Chat 不设置时正常工作。
- **检索响应**：增加可选 `rerank_score`，保留 `score` 的现有含义；Chat 的 sources 载荷仍是命中列表，不改变 SSE 事件结构。

## 失败处理与可观测性

单次 rerank 失败采用 fail-open：返回原始向量召回结果及排序，不让可选的精排服务中断核心 Search/Chat 功能。必须写结构化 warning，标明使用了向量排序 fallback；成功则记录 profile、provider、候选数、最终条数及耗时。模型连通性测试失败须明确返回失败，不能使用 fallback 伪装成测试成功。

## 验证方案

1. 协议单测：覆盖硅基流动与 Cohere 的请求 URL、认证、请求字段、响应解析、错误状态和格式错误。
2. 检索服务单测：验证默认模型存在时扩大召回并按 rerank 顺序排序；未配置时与现有行为一致；`threshold` 只作用于向量分数；保留原始 `score` 并填入 `rerank_score`。
3. 降级测试：验证超时、HTTP 错误和非法响应都会回退到原向量顺序，并记录告警。
4. API/服务回归：覆盖 Search 与 Chat 两处共用路径，确认 sources、图片溯源、vault/embedding 绑定及 `top_k` 返回条数不变。
5. 离线质量评估：用标注 query-document 集比较 rerank 前后 Recall@K、MRR 或 nDCG，并记录额外延迟及 API 调用成本。未有标注集前，不宣称准确率已提升。

## 非目标

- 不更换 embedding 模型、不重建索引、不修改 chunking 或 Chroma collection。
- 不在首版支持本地 cross-encoder、LLM-as-reranker、逐请求关闭参数或用户可调候选数。
- 不改变无 rerank profile 时现有的 Search/Chat 结果格式和行为；唯一新增响应字段为可选 `rerank_score`。

## 实施前需核实

- 确认硅基流动与 Cohere 的当前 endpoint 路径、认证头、请求字段及响应格式，并把真实协议行为固化进适配器测试。
- 确认默认 rerank profile 的 enabled/default 组合在模型管理 UI 中提示明确，避免用户误以为新增但未设默认的配置已自动生效。
