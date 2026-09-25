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

export async function apiFetch(path, options = {}) {
  // FormData 的 Content-Type 必须由浏览器带（含 multipart boundary），手写会破坏解析
  const isForm = typeof FormData !== 'undefined' && options.body instanceof FormData
  const headers = { ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...(options.headers || {}) }
  const token = getToken()
  const apiKey = getApiKey()
  if (token) headers['Authorization'] = `Bearer ${token}`
  else if (apiKey) headers['X-API-Key'] = apiKey

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const raw = await res.text().catch(() => '')
    const err = new Error(`HTTP ${res.status} ${raw}`)
    // 结构化错误：调用方需要区分 409/404/502 等（如提交作业撞上「同库已有作业在跑」）
    err.status = res.status
    try {
      err.body = raw ? JSON.parse(raw) : null
    } catch {
      err.body = null
    }
    throw err
  }
  if (res.status === 204) return null
  const text = await res.text()
  return text ? JSON.parse(text) : null   // 202 也有 body（run_id），但不能假定总有
}

export { API_BASE }

// ===== Vault 与作业（异步 job 模型，见 M03 §5.13 / M06 §5.5）=====
// 写入类端点一律返回 202 + run_id，**不代表已完成**；进度走 getRun 轮询。
export const vaultsApi = {
  list: () => apiFetch('/vaults'),
  create: (payload) => apiFetch('/vaults', { method: 'POST', body: JSON.stringify(payload) }),
  get: (id) => apiFetch(`/vaults/${id}`),
  remove: (id) => apiFetch(`/vaults/${id}`, { method: 'DELETE' }),

  /** 上传 zip：走 multipart（apiFetch 会自动让浏览器设 Content-Type）。 */
  upload: (name, file) => {
    const fd = new FormData()
    fd.append('name', name)
    fd.append('file', file)
    return apiFetch('/vaults/upload', { method: 'POST', body: fd })
  },

  /**
   * 提交同步作业 → 202 { run_id, vault_id, status }。
   * 同 vault 已有作业在跑 → 409（**不排队**），err.status === 409 且
   * err.body 里带 existing_run_id —— 前端应跳到那个任务的进度视图，而不是报错（M06 ADR-8）。
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

// ===== 多模型管理（见 docs/design.md §18）=====
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
