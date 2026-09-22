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
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  const apiKey = getApiKey()
  if (token) headers['Authorization'] = `Bearer ${token}`
  else if (apiKey) headers['X-API-Key'] = apiKey

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${detail}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export { API_BASE }

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
