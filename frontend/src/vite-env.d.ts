/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Grafana dashboard 호스트 (Phase 2.2.10 RuntimeMonitor iframe). */
  readonly VITE_GRAFANA_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
