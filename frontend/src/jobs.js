// 作业（run）的前端共用常量与纯函数 —— 阶段中文化 / 状态语义 / 进度形态判定。
//
// 为什么单独一个模块：这些映射被三处共用（Vault 卡片内嵌、任务页、作业详情抽屉），
// 散落在组件里必然会漂移 —— 比如任务页认得 aborted，卡片却当成 running。
//
// 契约来源：M07 §5.4（任务与进度视图）、M03 §5.13.3（进度模型）、M03 §5.13.6（三类失败终态）。
// 后端出参字段见 SyncRunOut / SyncRunDetail（app/models/schemas.py）。

/** 阶段顺序（固定可见：让用户知道还有几步要走）。null/未知阶段不在此表。 */
export const STAGES = [
  { key: 'queued', label: '排队中', hint: '等待该 vault 的前一个作业结束（同库串行）' },
  { key: 'probe', label: '检查源', hint: '校验 vault 路径 / 远端是否可达' },
  { key: 'scan', label: '扫描文件', hint: '遍历目录并应用过滤规则；总量此时不可知' },
  { key: 'diff', label: '比对变更', hint: '用 size+mtime 快判、content_hash 复核' },
  { key: 'plan', label: '生成计划', hint: '分类四类变更并做删除护栏判定' },
  { key: 'plan_ready', label: '等待确认', hint: 'dry_run 的终点：计划已生成，等你点「执行」' },
  { key: 'index', label: '建立索引', hint: '解析 → 分块 → 嵌入 → 写入，主要耗时区' },
  { key: 'prune', label: '清理删除', hint: '护栏通过后删除磁盘上已不存在的文件' },
  { key: 'done', label: '完成', hint: '' },
]

const STAGE_MAP = Object.fromEntries(STAGES.map((s) => [s.key, s]))

/** 阶段中文名（未知阶段原样返回，方便排查新增阶段）。 */
export function stageLabel(stage) {
  return STAGE_MAP[stage]?.label || stage || '—'
}

/** 阶段在当前模式下是否会被跳过 —— 用于把阶段列表画成「已过 / 当前 / 待办 / 不适用」。 */
export function stageHint(stage) {
  return STAGE_MAP[stage]?.hint || ''
}

/**
 * 状态语义（七态，缺一不可）：
 *   queued/running      进行中
 *   success             全部成功
 *   partial             跑完了，但有文件失败（**不是**失败，结果可用）
 *   failed              程序异常中断
 *   cancelled           用户主动停止（已完成的部分保留）
 *   aborted             进程崩溃残留（启动清理标记）
 * 后三者语义完全不同，文案不可混用（M03 §5.13.6）。
 */
export const STATUS = {
  queued: { label: '排队中', tone: 'info', running: true },
  running: { label: '进行中', tone: 'info', running: true },
  success: { label: '已完成', tone: 'ok', running: false },
  partial: { label: '部分完成', tone: 'warn', running: false },
  failed: { label: '失败', tone: 'danger', running: false },
  cancelled: { label: '已取消', tone: 'muted', running: false },
  aborted: { label: '已中断', tone: 'danger', running: false },
}

export function statusInfo(status) {
  return STATUS[status] || { label: status || '—', tone: 'muted', running: false }
}

/** 是否已到终态（轮询据此停表；见 §5.4.5「不要空转」）。 */
export function isTerminal(status) {
  return !statusInfo(status).running
}

/** 是否处于「已受理取消、尚未停稳」——此时按钮要禁用并显示「正在停止…」。 */
export function isCancelling(run) {
  return !!run?.cancelling && !isTerminal(run?.status)
}

/**
 * 进度条形态（§5.4.2）：
 *   'badge'         终态 → 收起进度条，换状态徽标 + 计数摘要
 *   'indeterminate' total === null → 不确定态滚动条（scan 阶段）
 *   'determinate'   total > 0 → processed / total 百分比
 *   'waiting'       其余（queued，total 也未定）
 * **绝不给不确定态硬编假分母。**
 */
export function progressShape(run) {
  if (!run) return 'waiting'
  if (isTerminal(run.status)) return 'badge'
  if (run.total === null || run.total === undefined) {
    return run.status === 'queued' ? 'waiting' : 'indeterminate'
  }
  return run.total > 0 ? 'determinate' : 'waiting'
}

/** 确定态的百分比（0–100；total 为 0/未知时返回 0，调用方应先判 progressShape）。 */
export function percent(run) {
  if (!run?.total || run.total <= 0) return 0
  return Math.min(100, Math.round(((run.processed || 0) / run.total) * 100))
}

/** 计数摘要，如「+2 ~1 -0 ⇥1」——sync 的四类动作一眼可读。 */
export function countsSummary(run) {
  if (!run) return ''
  return `+${run.adds || 0} ~${run.updates || 0} -${run.deletes || 0} ⇥${run.moves || 0}`
}

/**
 * 轮询间隔（毫秒，§5.4.5）：
 *   取消中 / 索引中 → faster（用户盯着看，值得更勤）
 *   queue 阶段      → slower（等锁可能要几十秒，密集轮询没意义）
 */
export function pollInterval(status, cancelling = false) {
  if (cancelling) return 500
  if (status === 'running') return 1000
  if (status === 'queued') return 2000
  return 1000
}

/** 「3 分钟前」这类相对时间；无值时返回空串（不显示假时间）。 */
export function relativeTime(iso) {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return `${Math.floor(diff / 86_400_000)} 天前`
}
