import { ref } from 'vue'

// 全局提示（T2.9 / 规范 §4.2）—— 「右上角（移动端顶部居上），3s 自动消失；
// 错误类不自动消失，需手动关闭」。
//
// 用模块级状态而不是 provide/inject：提示是全局的（任何页面、任何异步回调都可能触发），
// 由 AppShell 顶层挂一个 AppToast 宿主即可，组件树深度无关。
// 跨端迁移：宿主换成 Toast API 的调用即可，本模块接口不变。

let seq = 0

export const toasts = ref([])

/** 自动消失时长（毫秒）；0 = 不自动消失。 */
const DURATION = {
  info: 3000,
  success: 3000,
  warn: 3000,
  danger: 0, // 错误必须人工确认，避免一闪而过
}

export function pushToast(message, tone = 'info', options = {}) {
  const id = (seq += 1)
  const duration = options.duration !== undefined ? options.duration : DURATION[tone] ?? 3000
  toasts.value = [...toasts.value, { id, message: String(message ?? ''), tone, duration }]
  if (duration > 0) {
    setTimeout(() => dismissToast(id), duration)
  }
  return id
}

export function dismissToast(id) {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

export const toast = {
  info: (message, options) => pushToast(message, 'info', options),
  success: (message, options) => pushToast(message, 'success', options),
  warn: (message, options) => pushToast(message, 'warn', options),
  error: (message, options) => pushToast(message, 'danger', options),
}
