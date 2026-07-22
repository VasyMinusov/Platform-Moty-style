import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      // Бэкенд (FastAPI) слушает на :8000 и НЕ имеет префикса /api в своих
      // роутерах (/auth, /challenges, /admin). Поэтому в dev мы срезаем
      // префикс /api, а в проде это делает nginx (см. nginx.conf).
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
