import { createRouter, createWebHistory } from 'vue-router'
import VaultManager from './components/VaultManager.vue'
import TasksView from './components/TasksView.vue'
import SearchView from './components/SearchView.vue'
import ChatView from './components/ChatView.vue'
import LoginView from './components/LoginView.vue'
import ModelsView from './components/ModelsView.vue'

// SPA 路由（history 模式）。后端需对未知路径兜底返回 index.html（见 app/main.py catch-all）。
//
// /tasks 是异步作业的观察入口：后端写入类端点都返回 202 + run_id（M03 §5.13），
// Vault 卡片只能看「当前这一个作业」，跨 vault 的全量视图与历史在这里。
const routes = [
  { path: '/', redirect: '/vaults' },
  { path: '/vaults', name: 'vaults', component: VaultManager },
  { path: '/tasks', name: 'tasks', component: TasksView },   // 支持 ?vault_id=&run_id= 直达某个作业
  { path: '/search', name: 'search', component: SearchView },
  { path: '/chat', name: 'chat', component: ChatView },
  { path: '/models', name: 'models', component: ModelsView },
  { path: '/login', name: 'login', component: LoginView },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
