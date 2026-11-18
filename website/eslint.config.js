import eslintPluginAstro from 'eslint-plugin-astro';
import typescriptEslintParser from '@typescript-eslint/parser';

export default [
  // Ignore patterns first
  {
    ignores: [
      'dist/',
      'node_modules/',
      '.astro/',
      'bun.lockb',
      '*.lock',
    ],
  },

  // Astro recommended configuration
  ...eslintPluginAstro.configs.recommended,

  // TypeScript and JavaScript files
  {
    files: ['**/*.{js,ts,tsx}'],
    languageOptions: {
      parser: typescriptEslintParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: { jsx: true },
      },
    },
    rules: {
      // General rules
      'no-console': 'warn',
      'no-unused-vars': 'warn',
      'prefer-const': 'error',
    },
  },
  {
    files: ['**/*.tsx'],
    rules: {
      // TypeScript checks React props/types and JSX references reliably.
      'no-unused-vars': 'off',
    },
  },
  {
    files: ['scripts/**/*.ts'],
    rules: { 'no-console': 'off' },
  },

  // Astro files specific configuration
  {
    files: ['**/*.astro'],
    rules: {
      // Astro specific rules
      'astro/no-conflict-set-directives': 'error',
      'astro/no-unused-define-vars-in-style': 'error',

      // Allow console in Astro files (for development)
      'no-console': 'off',
    },
  },
];
