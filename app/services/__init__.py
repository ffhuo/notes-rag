"""业务编排层。

按 M03 §5.6 的三层职责划分（调用方向单向，不可反向 import）：

- `run_service`       作业层：何时跑、跑到哪了、能不能停（进度 / 取消 / 终态 / 启动清理）
- `sync_service`      对账层：要动哪些文件、允不允许删（判据 / 护栏 / dry_run / doctor）
- `ingest_service`    原语层：单个文件怎么进 / 出索引（解析 → 分块 → 嵌入 → 写入）
- `vault_service`     提交侧：解析 vault 源为本机路径 → 委托 run_service.submit
- `model_service`     模型配置解析（LLM / Embedding 的默认项与运行时回退）
- `watcher`（二期）   文件系统事件 → 仅标脏并提交作业，不自己判定变更

依赖方向：run_service → sync_service → ingest_service；
vault_service → run_service；watcher → run_service。
"""
