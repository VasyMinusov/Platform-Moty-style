import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      // Backend напрямую на :8000 не доступен (порт не публикуется),
      // поэтому проксируем /api/* на nginx (порт 80), который срежет
      // префикс /api/ и проксирует в backend:8000.
      '/api': {
        target: 'http://localhost',
        changeOrigin: false,
        // Прокидываем исходный Host клиента в X-Forwarded-Host, чтобы
        // backend формировал URL инстансов относительно того адреса,
        // по которому клиент пришёл (Wi-Fi или LAN за роутером).
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            if (req.headers.host) {
              proxyReq.setHeader('X-Forwarded-Host', req.headers.host)
            }
          })
        },
      },
    },
  },
})