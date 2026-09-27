import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

// 设计令牌与基础样式（顺序：令牌定义在前，基线在后）
import './styles/tokens.css'
import './styles/base.css'

import { initTheme } from './theme'

// 挂载全局：API 客户端在 src/api.js 中统一注入 X-API-Key / Bearer JWT
import './api'

// 挂载前应用主题（品牌 + 明暗），避免首帧主题闪烁（见 docs/ui-spec.md §2.8）
initTheme()

createApp(App).use(router).mount('#app')
