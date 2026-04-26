import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type SecurityEventKind =
  | "IP_MULTI_KEY"
  | "KEY_HIGH_4XX"
  | "IP_BURST"
  | "TLS_FAIL"
  | "OTHER";

export type SecurityEventSeverity = "INFO" | "WARN" | "ERROR" | "CRITICAL";

export interface SecurityEventOut {
  event_id: number;
  kind: SecurityEventKind;
  severity: SecurityEventSeverity;
  api_key_id: number | null;
  ip_addr: string | null;
  user_agent: string | null;
  details_json: Record<string, unknown>;
  occurred_at: string;
}

export interface SecurityEventParams {
  kind?: SecurityEventKind | null;
  severity?: SecurityEventSeverity | null;
  limit?: number;
  offset?: number;
}

export function useSecurityEvents(params: SecurityEventParams = {}) {
  return useQuery({
    queryKey: ["security-events", params],
    queryFn: () =>
      apiRequest<SecurityEventOut[]>("/v1/security-events", {
        params: {
          kind: params.kind ?? undefined,
          severity: params.severity ?? undefined,
          limit: params.limit ?? 100,
          offset: params.offset ?? 0,
        },
      }),
    refetchInterval: 30_000,
  });
}
