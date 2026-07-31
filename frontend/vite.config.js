import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// AgentFlow 前端（A8）：dev 端口 5176，/api 代理到后端 8020
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5176,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8020', changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          vue: ['vue', 'vue-router'],
          echarts: ['echarts'],
          marked: ['marked'],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/tests/**/*.test.js'],
  },
})
