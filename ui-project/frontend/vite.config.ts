import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器：/api 与 /ws 代理到本地 FastAPI 后端（8210 端口）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8210', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8210', ws: true }
    }
  }
})
