import type {RsbuildConfig} from '@rsbuild/core';

export const tradingTheme = {
  colors: {
    background: '#1d1d1f',
    surface: '#2c2c2e',
    surfaceHover: '#3a3a3c',
    border: 'rgba(255, 255, 255, 0.08)',
    text: '#f5f5f7',
    textSecondary: '#a1a1a6',
    accent: '#0a84ff',
    success: '#30d158',
    danger: '#ff453a',
    warning: '#ffd60a',
  },
  fonts: {
    display: "'JetBrains Mono', 'Fira Code', monospace",
    body: "'Inter', -apple-system, sans-serif",
    mono: "'JetBrains Mono', 'Fira Code', monospace",
  },
};

export const createWebConfig = (): RsbuildConfig => ({
  plugins: [
    {
      name: 'plugin-react',
    },
    {
      name: 'plugin-svgr',
    },
  ],
  output: {
    distPath: {
      root: 'dist',
    },
    assetPrefix: '/',
    htmlTemplate: './src/index.html',
  },
  source: {
    alias: {
      '@': './src',
    },
  },
  tools: {
    postcss: {
      postcssOptions: {
        plugins: ['autoprefixer'],
      },
    },
  },
});

export const defineConfig = {
  createWebConfig,
  tradingTheme,
};
