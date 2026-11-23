import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

const proxyTarget = process.env.VITE_PROXY_TARGET || 'http://localhost:8000';
// Packages grouped into the `vendor` chunk: the former object-form manualChunks entries plus
// their transitive deps (scheduler; react-router, which react-router-dom 7 re-exports).
const VENDOR_CHUNK_TEST =
  /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/;
const devPort = Number(process.env.VITE_PORT) || 3000;

export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/static/' : '/',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    extensions: ['.mjs', '.js', '.mts', '.ts', '.jsx', '.tsx', '.json'],
  },
  // Exclude test dependencies from Vite's dependency optimization
  optimizeDeps: {
    exclude: [
      '@playwright/test',
      'playwright',
      'playwright-core',
      '@testing-library/react',
      '@testing-library/jest-dom',
      '@testing-library/user-event',
      'vitest',
    ],
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
  build: {
    outDir: './static/', // Change output directory
    sourcemap: true,
    emptyOutDir: true,
    assetsDir: "", // Customize assets directory
    manifest: true, // Generate manifest file
    // `rollupOptions` is deprecated in Vite 8 (Rolldown); `codeSplitting` replaces manualChunks.
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [{ name: 'vendor', test: VENDOR_CHUNK_TEST }],
        },
      },
    },
  },
  server: {
    port: devPort,
    // Exclude test files from file watching to prevent bundling errors
    watch: {
      ignored: [
        '**/*.test.ts',
        '**/*.test.tsx',
        '**/*.spec.ts',
        '**/*.spec.tsx',
        '**/test/**',
        '**/tests/**',
        '**/__tests__/**',
      ],
    },
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
        secure: false,
      },
      '/docs': {
        target: proxyTarget,
        changeOrigin: true,
        secure: false,
      },
      '/redoc': {
        target: proxyTarget,
        changeOrigin: true,
        secure: false,
      },
    },
  },
})); 