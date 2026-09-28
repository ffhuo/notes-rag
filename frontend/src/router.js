import { createRouter, createWebHistory } from 'vue-router'
import VaultManager from './components/VaultManager.vue'
import TasksView from './components/TasksView.vue'
import SearchView from './components/SearchView.vue'
import ChatView from './components/ChatView.vue'
import ModelsView from './components/ModelsView.vue'
import ApiKeysView from './components/ApiKeysView.vue'

// SPA 路由（history 模式）。后端需对未知路径兜底返回 index.html（见 app/main.py catch-all）。
//
// /tasks 是异步作业的观察入口：后端写入类端点都返回 202 + run_id（M03 §5.13），
// Vault 卡片只能看「当前这一个作业」，跨 vault 的全量视图与历史在这里。
//
// meta.title 是页面标题的单一来源，顶栏与侧栏导航共用（避免两处文案漂移）。
//
// 鉴权不占路由：登录 / 注册 / 填 Key 统一由全局弹窗承担（见 src/auth.js、components/AuthGate.vue），
// 这样任何页面都无需重复写守卫，未登录时直接拿不到主界面。
const routes = [
  { path: '/', redirect: '/vaults' },
  { path: '/vaults', name: 'vaults', component: VaultManager, meta: { title: '知识库' } },
  { path: '/tasks', name: 'tasks', component: TasksView, meta: { title: '任务与进度' } },   // 支持 ?vault_id=&run_id= 直达某个作业
  { path: '/search', name: 'search', component: SearchView, meta: { title: '检索' } },
  { path: '/chat', name: 'chat', component: ChatView, meta: { title: '问答' } },
  { path: '/models', name: 'models', component: ModelsView, meta: { title: '模型管理' } },
  // 用户级 API Key（agent 接入鉴权）：签发 / 撤销，供 WorkBuddy 等使用（docs/mcp-guide.md）
  { path: '/keys', name: 'keys', component: ApiKeysView, meta: { title: 'API Keys' } },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})

/**
 * 侧栏导航项（顺序即展示顺序）。
 * label 取自对应路由的 meta.title、to 取自路由 path —— 文案与路径都只有一份来源，
 * 侧栏组件不再重写一遍导航文案（避免两处漂移）。
 * icon 名与路由 name 同名，见 src/icons.js。
 */
export const NAV_ITEMS = ['vaults', 'tasks', 'search', 'chat', 'models', 'keys'].map((name) => {
  const target = routes.find((r) => r.name === name)
  return { name, to: target.path, label: target.meta.title, icon: name }
})
