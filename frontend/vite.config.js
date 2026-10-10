import { defineConfig } from 'vite';
export default defineConfig({
  base: '/Gerstep/',
  server: { proxy: { '/Gerstep/api': { target: 'http://127.0.0.1:9081', ws: true } } },
  build: { target: 'es2020', sourcemap: false },
});
