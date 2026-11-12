import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({ plugins: [react()], base: './', build: { outDir: '../e7_assistant/assets/web', emptyOutDir: true } })
