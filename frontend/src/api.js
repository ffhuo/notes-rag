// API 客户端：统一 baseURL = /api/v1，自动带鉴权头。
// - 单用户模式：localStorage 存 nr_api_key，请求头 X-API-Key
// - 多用户模式：登录后存 nr_token，请求头 Authorization: Bearer <token>
const API_BASE = '/api/v1'

function getApiKey() {
  return localStorage.getItem('nr_api_key') || ''
}
function getToken() {
  return localStorage.getItem('nr_token') || ''
}

export function setApiKey(key) {
  if (key) localStorage.setItem('nr_api_key', key)
  else localStorage.removeItem('nr_api_key')
}
export function setToken(token) {
  if (token) localStorage.setItem('nr_token', token)
  else localStorage.removeItem('nr_token')
}

export const hasToken = () => !!getToken()
export const hasApiKey = () => !!getApiKey()

/** 清空本地凭据（退出登录、token 失效时调用）。 */
export function clearCredentials() {
  setToken('')
  setApiKey('')
}

/**
 * 构造鉴权头。抽出来给流式请求（transport/chat.js）复用 —— 鉴权规则只能有一份，
 * 否则「SSE 走 fetch 手写头」迟早与 apiFetch 漂移。
 */
export function authHeaders(extra = {}) {
  const headers = { ...extra }
  const token = getToken()
  const apiKey = getApiKey()
  if (token) headers['Authorization'] = `Bearer ${token}`
  else if (apiKey) headers['X-API-Key'] = apiKey
  return headers
}

export async function apiFetch(path, options = {}) {
  // FormData 的 Content-Type 必须由浏览器带（含 multipart boundary），手写会破坏解析
  const isForm = typeof FormData !== 'undefined' && options.body instanceof FormData
  const headers = authHeaders(isForm ? {} : { 'Content-Type': 'application/json' })
  Object.assign(headers, options.headers || {})

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    // 401 = 凭据失效（JWT 过期 / key 被改）：全局广播，由 auth 层收回界面并弹鉴权弹窗
    if (res.status === 401 && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('nr:unauthorized'))
    }
    const raw = await res.text().catch(() => '')
    const err = new Error(`HTTP ${res.status} ${raw}`)
    // 结构化错误：调用方需要区分 409/404/502 等（如提交作业撞上「同库已有作业在跑」）
    err.status = res.status
    try {
      err.body = raw ? JSON.parse(raw) : null
    } catch {
      err.body = null
    }
    // FastAPI 的业务信息全在 body.detail 里，外层还有一层信封（{"detail": …}）：
    // 直接读 err.body.xxx 恒为 undefined（曾因此让「跟着已有作业跳转」成了死代码）。
    // message 也从 detail 里取，否则界面上会出现
    // 「HTTP 409 {"detail":{"existing_run_id":12}}」这种没人看得懂的原文。
    err.detail = err.body?.detail ?? null
    if (typeof err.detail === 'string') err.message = err.detail
    else if (typeof err.detail?.message === 'string') err.message = err.detail.message
    throw err
  }
  if (res.status === 204) return null
  const text = await res.text()
  return text ? JSON.parse(text) : null   // 202 也有 body（run_id），但不能假定总有
}

export { API_BASE }

// ===== 鉴权（见 docs/design.md §17.3）=====
// mode 是**免鉴权**探测端点：前端据此决定「直接进入 / 填 API Key / 登录注册」。
export const authApi = {
  mode: () => apiFetch('/auth/mode'),
  me: () => apiFetch('/auth/me'),
  login: (username, password) =>
    apiFetch('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  register: (username, password) =>
    apiFetch('/auth/register', { method: 'POST', body: JSON.stringify({ username, password }) }),

  // ===== 用户级 API Key（agent 接入鉴权，见 docs/mcp-guide.md / M06 §5.7）=====
  // 明文 key 只在 create 响应出现一次：调用方必须立刻弹窗展示 + 复制，
  // 服务端只存 sha256 —— 关掉弹窗就再也拿不到，丢失只能撤销重建。
  listApiKeys: () => apiFetch('/auth/api-keys'),
  createApiKey: (name = '') =>
    apiFetch('/auth/api-keys', { method: 'POST', body: JSON.stringify({ name }) }),
  /** 撤销 = 软删除：立即失效（使用该 key 的 agent 马上 401），记录保留供审计。 */
  revokeApiKey: (id) => apiFetch(`/auth/api-keys/${id}`, { method: 'DELETE' }),
}

// ===== Vault 与作业（异步 job 模型，见 M03 §5.13 / M06 §5.5）=====
// 写入类端点一律返回 202 + run_id，**不代表已完成**；进度走 getRun 轮询。
export const vaultsApi = {
  list: () => apiFetch('/vaults'),
  create: (payload) => apiFetch('/vaults', { method: 'POST', body: JSON.stringify(payload) }),
  get: (id) => apiFetch(`/vaults/${id}`),
  remove: (id) => apiFetch(`/vaults/${id}`, { method: 'DELETE' }),

  /** 改 name / filters（source_value 不可改）；filters 传 null = 清空过滤。 */
  update: (id, patch) => apiFetch(`/vaults/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),

  /**
   * 列一层子目录（目录树懒加载）。
   * @param {string} path 根目录绝对路径（通常是 vault 在服务器上 / 解压后的目录）
   * @param {string} rel  相对根目录的子路径；'' 表示根目录本身
   */
  browse: (path, rel = '') =>
    apiFetch(`/vaults/browse?path=${encodeURIComponent(path)}&rel=${encodeURIComponent(rel)}`),

  /** 上传 zip：走 multipart（apiFetch 会自动让浏览器设 Content-Type）。
   *  file 可以是 File，也可以是前端打包出的 Blob —— Blob 没有 name，
   *  必须显式给文件名，否则后端只能拿到 "blob"（校验靠魔数，但报错信息会难懂）。 */
  upload: (name, file, filename = 'vault.zip') => {
    const fd = new FormData()
    fd.append('name', name)
    fd.append('file', file, file.name || filename)
    return apiFetch('/vaults/upload', { method: 'POST', body: fd })
  },

  /**
   * 提交同步作业 → 202 { run_id, vault_id, status }。
   * 同 vault 已有作业在跑 → 409（**不排队**），err.status === 409 且
   * err.detail 里带 existing_run_id —— 前端应跳到那个任务的进度视图，而不是报错（M06 ADR-8）。
   */
  submitSync: (id, payload = {}) =>
    apiFetch(`/vaults/${id}/sync`, { method: 'POST', body: JSON.stringify(payload) }),

  /** 全量重建（= submitSync 的 mode="rebuild" 别名）；换 embedding 必须走这条。 */
  reindex: (id, embedProfile = null) =>
    apiFetch(`/vaults/${id}/reindex${embedProfile ? `?embed_profile=${encodeURIComponent(embedProfile)}` : ''}`, {
      method: 'POST',
    }),

  /** 历史作业列表（含运行中；运行中由前端置顶，不在 SQL 层过滤）。 */
  listRuns: (id, limit = 20) => apiFetch(`/vaults/${id}/runs?limit=${limit}`),

  /** 作业详情与进度轮询（前端 1s 轮询；终态后停表）。 */
  getRun: (id, runId) => apiFetch(`/vaults/${id}/runs/${runId}`),

  /** 请求取消 → 204；已终态 → 409。**协作式**，在文件边界才真正停止。 */
  cancelRun: (id, runId) => apiFetch(`/vaults/${id}/runs/${runId}/cancel`, { method: 'POST' }),

  /** 三向一致性自检（ghost 向量 / 缺失向量 / 孤儿笔记 / 模型错配）。 */
  doctor: (id, repair = false) =>
    repair
      ? apiFetch(`/vaults/${id}/doctor?repair=true`, { method: 'POST' })
      : apiFetch(`/vaults/${id}/doctor`),
}

// ===== 对话历史（问答页「历史记录」，见 docs/design.md §4.3）=====
// 会话标题由后端从首条提问派生（库里没有 title 列）；时间字段是 13 位毫秒时间戳。
export const conversationsApi = {
  /** 会话列表，最近在前：[{id, title, message_count, created_at}] */
  list: (limit = 50) => apiFetch(`/conversations?limit=${limit}`),

  /** 某会话的消息，按时间升序：[{id, role, content, created_at}]（不含来源，见后端 MessageOut） */
  messages: (id) => apiFetch(`/conversations/${id}/messages`),
}

// ===== 语音转写（见 docs/design.md §4.3 Chat / §18 多模型）=====
// 音频**不落库**：上传即转写、返回文本，前端把文本填进输入框（不自动发送）。
// 目标端点由后端按 model_profiles(kind='asr') 解析；没配置会返回 409 并说明该怎么做。
export const audioApi = {
  /**
   * @param {Blob} blob MediaRecorder 的产物（见 recorder.js 的 startRecording）
   * @param {string} filename 必须带扩展名，上游按它推断容器格式
   * @param {{language?: string}} options language 形如 'zh' / 'en'，留空由模型自判
   */
  transcribe: (blob, filename = 'clip.webm', { language } = {}) => {
    const fd = new FormData()
    fd.append('file', blob, filename)
    const qs = language ? `?language=${encodeURIComponent(language)}` : ''
    return apiFetch(`/audio/transcribe${qs}`, { method: 'POST', body: fd })
  },
}

// ===== 多模型管理（见 docs/design.md §10 模块索引 M08）=====
// 一个模型配置 = model_profiles 一条记录；kind: 'llm' | 'embed'
export const modelsApi = {
  list: (kind) => apiFetch(`/models${kind ? `?kind=${kind}` : ''}`),
  create: (payload) =>
    apiFetch('/models', { method: 'POST', body: JSON.stringify(payload) }),
  update: (id, patch) =>
    apiFetch(`/models/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id) => apiFetch(`/models/${id}`, { method: 'DELETE' }),
  setDefault: (id) => apiFetch(`/models/${id}/default`, { method: 'POST' }),
  test: (id) => apiFetch(`/models/${id}/test`, { method: 'POST' }),
  testUnsaved: (payload) =>
    apiFetch('/models/test', { method: 'POST', body: JSON.stringify(payload) }),
}
