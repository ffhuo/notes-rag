import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 开发：Vite dev server 代理 /api 到后端（http://127.0.0.1:8000），前后端分离联调。
// 构建：产物直接输出到 ../app/static，后端 FastAPI 用 StaticFiles(html=True) 托管同源，
//       免 CORS；SPA 子路由靠后端兜底返回 index.html（见后端 app/main.py 的 catch-all）。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: fileURLToPath(new URL('../app/static', import.meta.url)),
    emptyOutDir: true,
  },
})
