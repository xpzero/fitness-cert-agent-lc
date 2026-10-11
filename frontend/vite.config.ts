import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const API_PATHS = ["/chat", "/kb", "/quiz", "/plan"];

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((p) => [p, { target: "http://localhost:8770", changeOrigin: true }])),
  },
  // 前后端分离后生产预览也走代理（此前由 FastAPI 同端口托管，已移除）
  preview: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PATHS.map((p) => [p, { target: "http://localhost:8770", changeOrigin: true }])),
  },
});
