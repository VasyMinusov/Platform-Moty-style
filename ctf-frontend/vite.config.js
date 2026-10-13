import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'

const shouldAnalyze = process.env.ANALYZE === 'true'

export default defineConfig({
  plugins: [
    react(),
    shouldAnalyze &&
      visualizer({
        filename: 'dist/stats.html',
        gzipSize: true,
        brotliSize: true,
        open: true,
      }),
  ].filter(Boolean),

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

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
        ws: true, 
        // Прокидываем исходный Host клиента в X-Forwarded-Host, чтобы
        // backend формировал URL инстансов относительно того адреса,
        // по которому клиент пришёл (Wi-Fi или LAN за роутером).
        rewrite: (path) => path.replace(/^\/api/, ''),
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
