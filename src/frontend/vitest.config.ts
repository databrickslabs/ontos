/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    extensions: ['.mjs', '.js', '.mts', '.ts', '.jsx', '.tsx', '.json'],
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    exclude: [
      'node_modules',
      'dist',
      '.idea',
      '.git',
      '.cache',
      '**/playwright.config.ts',
      '**/src/tests/**/*.spec.ts', // Exclude Playwright E2E tests from src/tests/
      '**/tests/**/*.spec.ts', // Exclude Playwright E2E tests from tests/
    ],
    testTimeout: 10000, // 10 second timeout per test
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      // Restrict the coverage universe to first-party source. Without an
      // explicit include, `all: true` lets v8 instrument runtime-imported
      // deps (e.g. @babel/runtime), which polluted lcov.info with ~1.3k
      // node_modules entries and made Codecov unable to resolve the
      // `frontend` flag (badge showed "unknown").
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        '**/node_modules/**',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/mockData',
        'src/components/ui/**', // Exclude Shadcn UI base components
        '**/*.test.{ts,tsx}',
        '**/*.spec.{ts,tsx}',
        'dist/',
        'coverage/',
        'playwright.config.ts',
        'vite.config.ts',
      ],
      all: true,
      // Gates set to current baseline floors (just under measured coverage)
      // to prevent regressions. Ratchet up as coverage improves toward the
      // 80% goal. Measured at time of writing: lines/statements 10.2%,
      // functions 36.1%, branches 72.1%.
      thresholds: {
        lines: 10,
        functions: 35,
        branches: 70,
        statements: 10,
      },
    },
  },
});
