import {defineConfig} from '@rsbuild/core';
import {pluginReact} from '@rsbuild/plugin-react';
import {pluginSvgr} from '@rsbuild/plugin-svgr';
import path from 'path';

export default defineConfig({
  plugins: [pluginReact(), pluginSvgr()],
  source: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    entry: {
      index: './src/main.tsx',
    },
  },
  output: {
    distPath: {
      root: './dist',
    },
    htmlTemplate: './src/index.html',
  },
  tools: {
    postcss: {
      postcssOptions: {
        plugins: ['autoprefixer'],
      },
    },
  },
  server: {
    // 固定端口，被占用时直接报错而不是自动递增（避免地址变来变去）。
    // 端口优先级：FRONTEND_PORT 环境变量（dev-start.sh 传入）> 默认 12000。
    // Kimi Work 预览卡片会通过 CLI --port 显式指定端口，不受此影响。
    port: Number(process.env.FRONTEND_PORT) || 12000,
    strictPort: true,
    proxy: {
      // 后端跑在本机，直接走 127.0.0.1，不依赖主机名解析或端口转发
      '/api': {
        target: 'http://127.0.0.1:12100',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:12100',
        ws: true,
      },
    },
  },
});
