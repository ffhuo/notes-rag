import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

// 挂载全局：API 客户端在 src/api.js 中统一注入 X-API-Key / Bearer JWT
import './api'

createApp(App).use(router).mount('#app')
