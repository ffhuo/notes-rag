"""业务·文件监听 — 本地 vault 的文件系统事件 → 触发增量同步（**二期预留**）。

状态：**仅契约，未实现**（一期用「手动同步 + 可选定时同步」覆盖日常需求）。

设计要点（M03 §5.10.2）——本模块有一条硬边界：

    watch 事件**只负责标记「这个 vault 脏了」**，不携带、也不决定
    「哪个文件变了、该怎么处理」。真正做什么完全由 sync_service 的对账 + 护栏决定。

触发方式：debounce 窗口结束后走**与其他路径完全相同的作业提交**
（`run_service.submit(..., trigger="watch")`），而不是直接调 `sync_service.sync_vault`。
理由：提交路径统一才有互斥（同 vault 不并发）、幂等（已有作业在跑不排队）、
进度与取消（用户能在任务视图里看到这次 watch 触发的同步）—— 这三件事都在作业层。

理由（为什么不能做成「事件直连增删」）：
1. 会产生**第二份变更判定逻辑**，必然与对账逻辑漂移（改一处忘一处）；
2. 事件本身不可靠：可能丢失 / 重复 / 乱序；跨平台语义有差异；
   **网络挂载（SMB/NFS、部分 Docker volume）通常根本不产生事件**；
3. Obsidian 保存是「写临时文件 + rename」，事件流会瞬时产生 create + delete + create，
   直连处理会把**正在保存**的文件判为「删除」；
4. 删除不可逆 —— 不能让不可靠的事件流直接驱动删除。

配套要求：
- debounce：单 vault 事件静默窗口 WATCH_DEBOUNCE_MS（默认 1000ms），窗口内事件合并为一次 sync；
- 永不绕过护栏：watch 触发的 sync 与手动 sync 走完全相同的三道删除护栏；
- 静默降级：git: / remote: / 网络挂载路径不启用 watch，退化为定时同步并记日志。

主要函数：
- async def start_watcher(vault) -> None: 启动监听（watchfiles.awatch 循环 + debounce）
- async def stop_watcher(vault_id: int) -> None: 停止监听
- def is_watchable(vault, local_path) -> bool: 判定该 vault 是否可监听（本地源且非网络挂载）

关联方案：docs/design.md §5.1.1（增量同步）。
完整触发矩阵与边界见设计文档库 M03 §5.10。
"""


async def start_watcher(vault) -> None:
    """启动对某 vault 的文件监听；事件仅用于「标脏 + debounce 后提交作业」。"""
    ...


async def stop_watcher(vault_id: int) -> None:
    """停止某 vault 的监听（删除 vault / 关闭 watch 时调用）。"""
    ...


def is_watchable(vault, local_path) -> bool:
    """是否可监听：仅 source_type=local 且不是网络挂载（SMB/NFS）时返回 True。"""
    ...
