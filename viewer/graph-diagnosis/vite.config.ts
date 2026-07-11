import { defineConfig } from 'vite';

export default defineConfig({
  base: '/static/graph-diagnosis/',
  define: {
    process: JSON.stringify({ env: { NODE_ENV: 'production' } }),
  },
  build: {
    emptyOutDir: true,
    outDir: '../static/graph-diagnosis',
    lib: {
      entry: 'src/main.tsx',
      name: 'CCWhatGraphDiagnosis',
      formats: ['iife'],
      fileName: () => 'graph-diagnosis.js',
    },
    rollupOptions: {
      output: {
        assetFileNames: (asset) => asset.name?.endsWith('.css')
          ? 'graph-diagnosis.css'
          : 'assets/[name]-[hash][extname]',
      },
    },
  },
});
