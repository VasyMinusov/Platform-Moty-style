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
      // ── Прокси /api/* на nginx (порт 80) ────────────────────────────
      //
      // ВАЖНО: rewrite НЕ применяется.
      //
      // Раньше (до интеграции с auth-service) Vite проксировал
      // напрямую в backend, у которого роутеры живут без префикса
      // /api — поэтому префикс срезался:
      //
      //     '/api': { rewrite: (p) => p.replace(/^\/api/, '') }
      //
      // Теперь архитектура другая:
      //
      //     браузер → nginx (:80) → backend (/api/*)
      //                            → auth-service (/api/v1/*)
      //
      // nginx маршрутизирует по префиксу /api. Если Vite его срежет,
      // запросы уйдут не туда:
      //
      //     /api/auth/me    → срез → /auth/me    → 500 (нет такого)
      //     /api/v1/auth/login → срез → /v1/auth/login → 404
      //
      // Поэтому префикс сохраняем как есть.
      '/api': {
        // nginx слушает на хосте, где запущен compose. Vite dev
        // крутится на том же хосте, что и docker compose → localhost.
        target: 'http://localhost',

        // changeOrigin=false: nginx получает оригинальный Host
        // (localhost:5173), и в логах видно реального клиента.
        // Если бы был true — Host стал бы 'localhost:80', и nginx
        // логировал бы «себя», а не dev-сервер.
        changeOrigin: false,

        // WebSocket (notifications/stream, competitions/stream).
        ws: true,

        // Прокидываем X-Forwarded-Host. Backend использует его для
        // формирования URL инстансов заданий: если студент зашёл
        // с 192.168.1.5:5173, инстанс будет на 192.168.1.5:30001,
        // а не на 127.0.0.1:30001.
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