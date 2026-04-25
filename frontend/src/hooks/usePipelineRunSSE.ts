import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/store/auth";

export interface NodeStateChangedEvent {
  pipeline_run_id: number;
  run_date: string;
  workflow_id: number;
  node_run_id: number;
  node_key: string;
  node_type: string;
  status: string;
  attempt_no: number;
  error_message: string | null;
}

interface SSEState {
  connected: boolean;
  lastEvent: NodeStateChangedEvent | null;
  errorCount: number;
}

/** 브라우저 EventSource 는 Authorization 헤더 미지원 — fetch-event-source 사용. */
export function usePipelineRunSSE(pipelineRunId: number | null): SSEState {
  const accessToken = useAuthStore((s) => s.accessToken);
  const qc = useQueryClient();
  const [state, setState] = useState<SSEState>({
    connected: false,
    lastEvent: null,
    errorCount: 0,
  });
  const ctrlRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (pipelineRunId == null || !accessToken) return;
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;

    fetchEventSource(`/v1/pipelines/runs/${pipelineRunId}/events`, {
      signal: ctrl.signal,
      headers: { Authorization: `Bearer ${accessToken}` },
      openWhenHidden: true,
      onopen: async (resp) => {
        if (resp.ok) {
          setState((s) => ({ ...s, connected: true }));
          return;
        }
        if (resp.status === 401 || resp.status === 403) {
          // 인증 만료 — 자동 재시도 중단.
          throw new Error(`SSE auth failed: ${resp.status}`);
        }
      },
      onmessage: (msg) => {
        if (msg.event === "ping") return;
        if (msg.event === "node.state.changed" && msg.data) {
          let payload: NodeStateChangedEvent | null = null;
          try {
            // backend 가 outer JSON string 에 inner JSON 한 번 더 감싸서 보냄.
            const outer = JSON.parse(msg.data);
            payload = typeof outer === "string" ? JSON.parse(outer) : outer;
          } catch (err) {
            console.warn("[SSE] failed to parse payload", err, msg.data);
            return;
          }
          if (payload) {
            setState((s) => ({ ...s, lastEvent: payload }));
            qc.invalidateQueries({
              queryKey: ["pipelines", "runs", pipelineRunId],
            });
          }
        }
      },
      onerror: (err) => {
        setState((s) => ({ ...s, connected: false, errorCount: s.errorCount + 1 }));
        // throw → 라이브러리가 재시도 중단. err 그대로 던지면 재시도 안 함.
        // 인증 만료 케이스는 onopen 에서 처리 — 여기선 재시도 허용 (일시적 네트워크).
        console.warn("[SSE] error", err);
      },
    }).catch((err) => {
      console.warn("[SSE] fatal", err);
      setState((s) => ({ ...s, connected: false }));
    });

    return () => {
      ctrl.abort();
      ctrlRef.current = null;
    };
  }, [pipelineRunId, accessToken, qc]);

  return state;
}
