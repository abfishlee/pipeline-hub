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
      // /v2 는 frontend SPA 라우트 (예: /v2/marts/designer) 와 backend API
      // (예: /v2/domains) 가 prefix 를 공유. 브라우저 네비게이션 (Accept:
      // text/html) 은 SPA 로, fetch/XHR (Accept: application/json 또는 */*)
      // 은 backend 로 분기.
      "/v2": {
        target: BACKEND,
        changeOrigin: true,
        bypass: (req) => {
          const accept = req.headers["accept"] ?? "";
          if (req.method === "GET" && accept.includes("text/html")) {
            return req.url; // SPA fallback (index.html 서빙)
          }
          return null; // proxy 실행
        },
      },
      "/public": BACKEND,
      "/healthz": BACKEND,
      "/readyz": BACKEND,
    },
  },
});
