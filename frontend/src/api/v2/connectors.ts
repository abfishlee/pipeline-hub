// Phase 6 Wave 1 — Public API Connector client.
// 어떤 REST API 도 등록 가능한 *generic* 그릇. KAMIS 는 *예시 데이터* 일 뿐.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export type HttpMethod = "GET" | "POST";
export type AuthMethod = "none" | "query_param" | "header" | "basic" | "bearer";
export type PaginationKind = "none" | "page_number" | "offset_limit" | "cursor";
export type ResponseFormat = "json" | "xml";
export type ConnectorStatus = "DRAFT" | "REVIEW" | "APPROVED" | "PUBLISHED";

export interface PublicApiConnector {
  connector_id: number;
  domain_code: string;
  resource_code: string;
  name: string;
  description: string | null;
  endpoint_url: string;
  http_method: HttpMethod;
  auth_method: AuthMethod;
  auth_param_name: string | null;
  secret_ref: string | null;
  request_headers: Record<string, string>;
  query_template: Record<string, unknown>;
  body_template: Record<string, unknown> | null;
  pagination_kind: PaginationKind;
  pagination_config: Record<string, unknown>;
  response_format: ResponseFormat;
  response_path: string | null;
  timeout_sec: number;
  retry_max: number;
  rate_limit_per_min: number;
  schedule_cron: string | null;
  schedule_enabled: boolean;
  status: ConnectorStatus;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConnectorIn {
  domain_code: string;
  resource_code: string;
  name: string;
  description?: string | null;
  endpoint_url: string;
  http_method?: HttpMethod;
  auth_method?: AuthMethod;
  auth_param_name?: string | null;
  secret_ref?: string | null;
  request_headers?: Record<string, string>;
  query_template?: Record<string, unknown>;
  body_template?: Record<string, unknown> | null;
  pagination_kind?: PaginationKind;
  pagination_config?: Record<string, unknown>;
  response_format?: ResponseFormat;
  response_path?: string | null;
  timeout_sec?: number;
  retry_max?: number;
  rate_limit_per_min?: number;
  schedule_cron?: string | null;
  schedule_enabled?: boolean;
}

export interface TestCallRequest {
  runtime_params?: Record<string, unknown>;
  max_pages?: number;
}

export interface TestCallResponse {
  success: boolean;
  http_status: number | null;
  row_count: number;
  duration_ms: number;
  request_summary: Record<string, unknown>;
  sample_rows: Record<string, unknown>[];
  error_message: string | null;
}

export interface ConnectorRunRow {
  run_id: number;
  run_kind: string;
  http_status: number | null;
  row_count: number;
  duration_ms: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

const BASE = "/v2/connectors/public-api";

export interface ListConnectorsParams {
  domain_code?: string;
  status?: ConnectorStatus;
  limit?: number;
}

export function useConnectors(params: ListConnectorsParams = {}) {
  return useQuery({
    queryKey: ["v2-connectors", params],
    queryFn: () =>
      apiRequest<PublicApiConnector[]>(BASE, {
        params: { ...params },
      }),
  });
}

export function useConnector(connectorId: number | null) {
  return useQuery({
    queryKey: ["v2-connectors", connectorId],
    enabled: connectorId != null,
    queryFn: () =>
      apiRequest<PublicApiConnector>(`${BASE}/${connectorId}`),
  });
}

export function useCreateConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ConnectorIn) =>
      apiRequest<PublicApiConnector>(BASE, { method: "POST", body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-connectors"] }),
  });
}

export function useUpdateConnector(connectorId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: ConnectorIn) =>
      apiRequest<PublicApiConnector>(`${BASE}/${connectorId}`, {
        method: "PATCH",
        body: req,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-connectors"] }),
  });
}

export function useDeleteConnector() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (connectorId: number) =>
      apiRequest<void>(`${BASE}/${connectorId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-connectors"] }),
  });
}

export function useTransitionConnector(connectorId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target_status: ConnectorStatus) =>
      apiRequest<PublicApiConnector>(`${BASE}/${connectorId}/transition`, {
        method: "POST",
        body: { target_status },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-connectors"] }),
  });
}

export function useTestCallConnector(connectorId: number) {
  return useMutation({
    mutationFn: (req: TestCallRequest = {}) =>
      apiRequest<TestCallResponse>(`${BASE}/${connectorId}/test`, {
        method: "POST",
        body: req,
      }),
  });
}

export function useConnectorRuns(connectorId: number | null, limit = 20) {
  return useQuery({
    queryKey: ["v2-connectors", connectorId, "runs", limit],
    enabled: connectorId != null,
    queryFn: () =>
      apiRequest<ConnectorRunRow[]>(`${BASE}/${connectorId}/runs`, {
        params: { limit },
      }),
  });
}
