// 作业状态色映射 —— 单一来源，供 AppStatusBadge / AppProgress / 侧栏状态区共用。
//
// 为什么单独成模块（对应 docs/ui-tasks.md §4.1）：状态语义只允许定义一次。
// 若各组件各写一份「状态 → 颜色」，aborted 迟早会在某处退化成 failed 的红色。
//
// 两套映射的分工：
//   · STATUS_TOKEN：已知状态 → 规范 §2.3 的专属状态令牌（八色，语义不同不共用颜色）
//   · TONE_TOKEN  ：状态未知时的粗粒度兜底（tone 由 jobs.js 给出）
// 由此消解 §4.1 记录的冲突：jobs.js 里 aborted 的 tone 仍是 danger（不擅自改公共语义），
// 但渲染时 aborted 命中专属令牌 --status-aborted，不会与 failed 同色。

import { statusInfo } from './jobs'

const STATUS_TOKEN = {
  queued: 'var(--status-queued)',
  running: 'var(--status-running)',
  plan_ready: 'var(--status-plan-ready)',
  success: 'var(--status-success)',
  partial: 'var(--status-partial)',
  failed: 'var(--status-failed)',
  cancelled: 'var(--status-cancelled)',
  aborted: 'var(--status-aborted)',
}

const TONE_TOKEN = {
  info: 'var(--color-info)',
  ok: 'var(--color-success)',
  warn: 'var(--color-warning)',
  danger: 'var(--color-danger)',
  muted: 'var(--color-text-muted)',
}

/** 作业状态色（CSS 变量表达式，可直接用于 style 绑定）。 */
export function statusColor(status) {
  if (status && STATUS_TOKEN[status]) return STATUS_TOKEN[status]
  return toneColor(statusInfo(status).tone)
}

/** 语义色调色（非作业场景的粗粒度提示色）。 */
export function toneColor(tone) {
  return TONE_TOKEN[tone] || TONE_TOKEN.muted
}
