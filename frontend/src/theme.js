// 主题运行时：品牌色 + 明暗两个正交维度（规范：docs/ui-spec.md §2.8）
//
// 跨端注意：
//   · 切换一律通过 class，不用 [data-*] 属性选择器
//     （小程序 WXSS 对属性选择器支持不可靠）
//   · 存储读写与 DOM 应用分离，便于 RN / 小程序替换实现（规范 §6.3）
//
// 令牌侧对应：tokens.css 的 .brand-* / .scheme-*

const STORAGE_KEY_BRAND = 'nr_theme_brand'
const STORAGE_KEY_SCHEME = 'nr_theme_scheme'

/** 预置品牌主题包（与 tokens.css 的 .brand-* 一一对应）。 */
export const BRANDS = [
  { id: 'blue', label: '经典蓝' },
  { id: 'indigo', label: '靛蓝' },
  { id: 'teal', label: '青绿' },
  { id: 'slate', label: '石板灰' },
  { id: 'violet', label: '紫罗兰' },
]

export const SCHEMES = [
  { id: 'light', label: '浅色' },
  { id: 'dark', label: '深色' },
]

const DEFAULT_BRAND = 'blue'

/* ---------- 存储（跨端时替换本段即可） ---------- */

function readStorage(key) {
  try {
    return localStorage.getItem(key) || ''
  } catch {
    return ''   // 隐私模式 / 存储被禁用
  }
}

function writeStorage(key, value) {
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch {
    /* 忽略：存储不可用时仅本次会话生效 */
  }
}

/* ---------- 读取 ---------- */

const isKnownBrand = (id) => BRANDS.some((b) => b.id === id)
const isKnownScheme = (id) => id === 'light' || id === 'dark'

/** 品牌：非法或未设置时回退默认。 */
export function getBrand() {
  const id = readStorage(STORAGE_KEY_BRAND)
  return isKnownBrand(id) ? id : DEFAULT_BRAND
}

/** 明暗：未手动设置时返回 null，表示「跟随系统」。 */
export function getScheme() {
  const id = readStorage(STORAGE_KEY_SCHEME)
  return isKnownScheme(id) ? id : null
}

function systemScheme() {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** 实际生效的明暗（含「跟随系统」）。 */
export function resolveScheme() {
  return getScheme() || systemScheme()
}

/* ---------- 应用 ---------- */

const ALL_BRAND_CLASSES = BRANDS.map((b) => `brand-${b.id}`)

/** 把主题写到根元素：只增删 class，不做任何样式计算。 */
function applyToDom(brand, scheme) {
  const root = document.documentElement
  root.classList.remove(...ALL_BRAND_CLASSES)
  root.classList.add(`brand-${brand}`)
  root.classList.remove('scheme-light', 'scheme-dark')
  root.classList.add(`scheme-${scheme}`)
}

/** 按当前偏好应用（幂等）。 */
export function applyTheme() {
  applyToDom(getBrand(), resolveScheme())
}

/* ---------- 变更 ---------- */

export function setBrand(id) {
  if (!isKnownBrand(id)) return
  writeStorage(STORAGE_KEY_BRAND, id)
  applyTheme()
}

/** id 传 null 表示恢复「跟随系统」。 */
export function setScheme(id) {
  if (id !== null && !isKnownScheme(id)) return
  writeStorage(STORAGE_KEY_SCHEME, id)
  applyTheme()
}

export function toggleScheme() {
  setScheme(resolveScheme() === 'dark' ? 'light' : 'dark')
}

/* ---------- 初始化 ---------- */

let mediaQuery = null

/**
 * 挂载前调用：立即应用主题，避免首帧主题闪烁。
 * 同时监听系统明暗变化，仅在用户未手动覆盖时随动。
 */
export function initTheme() {
  applyTheme()

  if (typeof window === 'undefined' || !window.matchMedia) return
  if (mediaQuery) return   // 幂等，避免 HMR 重复叠加监听

  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  const onChange = () => {
    if (!getScheme()) applyTheme()   // 仅「跟随系统」时随动
  }
  if (mediaQuery.addEventListener) mediaQuery.addEventListener('change', onChange)
  else if (mediaQuery.addListener) mediaQuery.addListener(onChange)   // 旧内核兜底
}
