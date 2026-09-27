// 剪贴板写入 —— 代码块「复制」与回答「复制」共用一份实现。
//
// 只走 navigator.clipboard：它需要安全上下文（https / localhost），本项目只有这两种
// 部署方式，所以不做 execCommand 兜底 —— 加了反而要维护两套失败语义。
// 返回 boolean 而不是抛异常：调用方只关心「成没成」，失败提示文案由 UI 决定。
export async function copyText(text) {
  const value = String(text ?? '')
  if (!value) return false
  try {
    await navigator.clipboard.writeText(value)
    return true
  } catch {
    return false
  }
}