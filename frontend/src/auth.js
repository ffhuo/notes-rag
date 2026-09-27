// 鉴权状态编排（见 docs/design.md §17.3）
//
// 启动流程：先调免鉴权的 GET /auth/mode 判定后端模式，再决定要什么凭据：
//   · 单用户 + 未配 API_KEY → 本机免鉴权，直接进主界面（「后台默认登录」）
//   · 单用户 + 配了 API_KEY → 校验本地已存 key，不通过则让用户填一次
//   · 多用户                → 校验本地已存 JWT，不通过则强制弹登录 / 注册
//
// 凭据读写留在 api.js（那是唯一的存储真相源），本模块只管状态流转。
import { computed, reactive } from 'vue'
import {
  authApi,
  clearCredentials,
  hasApiKey,
  hasToken,
  setApiKey,
  setToken,
} from './api'

/**
 * status 取值：
 *   checking —— 正在探测/校验，界面暂不可用
 *   ok       —— 凭据可用，进入主界面
 *   api-key  —— 单用户模式但服务端配了 API_KEY，需要用户填
 *   login    —— 多用户模式且未登录，需要登录或注册
 *   error    —— 模式探测失败（后端不可达），弹窗给出原因与重试
 */
const state = reactive({
  status: 'checking',
  multiuser: false,
  user: null,
  error: '',
})

export const authState = state

/** 界面是否可用：未 ready 时 App.vue 不渲染主界面，弹窗也关不掉。 */
export const isReady = computed(() => state.status === 'ok')

/** 用本地已存凭据换取身份；失败即视为凭据不可用（由调用方决定后续）。 */
async function verifyCredentials() {
  state.user = await authApi.me()
  state.status = 'ok'
  state.error = ''
}

/** 按探测结果决定「直接放行 / 去填 key / 去登录」。 */
function routeByMode(mode) {
  state.multiuser = !!mode.multiuser

  // 单用户且服务端未配 key：本机免鉴权，无需任何输入
  if (!mode.multiuser && !mode.api_key_required) {
    state.user = { uid: 'default', username: 'default', is_admin: true }
    state.status = 'ok'
    return
  }

  const need = mode.multiuser ? 'login' : 'api-key'
  const has = mode.multiuser ? hasToken() : hasApiKey()
  if (!has) {
    state.status = need
    return
  }

  verifyCredentials().catch(() => {
    // 本地凭据已失效（key 被改 / JWT 过期）：清掉再要求重新提供
    clearCredentials()
    state.status = need
  })
}

/** 启动时调用一次；失败时停留在弹窗里并给出可重试的错误提示。 */
export async function initAuth() {
  state.status = 'checking'
  state.error = ''
  try {
    routeByMode(await authApi.mode())
  } catch (e) {
    state.status = 'error'
    state.error = `无法连接后端服务：${e.message}`
  }
}

/** 多用户：登录并进入。 */
export async function login(username, password) {
  const res = await authApi.login(username, password)
  setToken(res.access_token)
  setApiKey('') // 切到 JWT 后不应残留单用户 key，否则请求头优先级会打架
  await verifyCredentials()
}

/** 多用户：注册后立即登录，避免让用户把账号密码再输一遍。 */
export async function register(username, password) {
  await authApi.register(username, password)
  await login(username, password)
}

/** 单用户：填 API Key（服务端配了 key 时才需要）。 */
export async function useApiKey(key) {
  const trimmed = key.trim()
  setApiKey(trimmed)
  try {
    await verifyCredentials()
  } catch (e) {
    setApiKey('')
    throw e
  }
}

let watching = false

/** 监听全局 401：令牌失效时收回界面并重新弹窗（幂等）。 */
export function watchUnauthorized() {
  if (watching || typeof window === 'undefined') return
  watching = true
  window.addEventListener('nr:unauthorized', () => {
    if (state.status !== 'ok') return // 弹窗已经在等用户了，不必重复处理
    clearCredentials()
    state.user = null
    state.status = state.multiuser ? 'login' : 'api-key'
  })
}
