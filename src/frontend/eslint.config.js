import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import react from 'eslint-plugin-react';
import i18next from 'eslint-plugin-i18next';
import eslintConfigPrettier from 'eslint-config-prettier';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'coverage', 'playwright-report'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended, eslintConfigPrettier],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    plugins: {
      react,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      i18next,
    },
    settings: {
      react: {
        version: 'detect',
      },
    },
    rules: {
      // React rules
      ...react.configs.recommended.rules,
      ...react.configs['jsx-runtime'].rules,
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],

      // TypeScript rules - relaxed for existing codebase
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-empty-object-type': 'off',

      // General rules
      'no-console': ['warn', { allow: ['warn', 'error'] }],

      // i18n guardrail (issue #471): flag user-facing string literals not routed
      // through t(...). Kept at 'warn' while the migration lands; flip to 'error'
      // once audit:i18n reaches ~0 to block regressions in CI.
      'i18next/no-literal-string': [
        'warn',
        {
          mode: 'jsx-text-only',
          'should-validate-template': false,
          message: 'Wrap user-facing text in t(...) — see src/i18n/README.md',
        },
      ],
    },
  },
  {
    // Non-UI code: tests, config, i18n plumbing, and stores/hooks with string
    // constants that are not user-facing. Keep the rule from adding noise here.
    files: [
      '**/*.test.{ts,tsx}',
      '**/tests/**',
      'src/i18n/**',
      '**/*.config.{ts,js}',
      'src/lib/**',
    ],
    rules: {
      'i18next/no-literal-string': 'off',
    },
  }
);
