import { createRouter, createWebHistory } from 'vue-router'
import VaultManager from './components/VaultManager.vue'
import SearchView from './components/SearchView.vue'
import ChatView from './components/ChatView.vue'
import LoginView from './components/LoginView.vue'
import ModelsView from './components/ModelsView.vue'

// SPA 路由（history 模式）。后端需对未知路径兜底返回 index.html（见 app/main.py catch-all）。
const routes = [
  { path: '/', redirect: '/vaults' },
  { path: '/vaults', name: 'vaults', component: VaultManager },
  { path: '/search', name: 'search', component: SearchView },
  { path: '/chat', name: 'chat', component: ChatView },
  { path: '/models', name: 'models', component: ModelsView },
  { path: '/login', name: 'login', component: LoginView },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
