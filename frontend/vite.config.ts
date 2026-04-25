import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// 백엔드 주소는 BACKEND_URL 환경변수로 override 가능 (기본 8000).
const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: false,
    proxy: {
      "/v1": BACKEND,
      "/healthz": BACKEND,
      "/readyz": BACKEND,
    },
  },
});
