import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    // Source maps включены — очень удобно для отладки в проде!
    sourcemap: true,
    rollupOptions: {
      output: {
        // Стабильные имена, чтобы было проще ориентироваться.
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name].[ext]',
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/graphql': 'http://localhost:4000',
    },
  },
});