// Phase 8.6 — Mock API (자체 검증용 외부 API 흉내).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export type MockResponseFormat = "json" | "xml" | "csv" | "tsv" | "text";

export interface MockEndpoint {
  mock_id: number;
  code: string;
  name: string;
  description: string | null;
  response_format: MockResponseFormat;
  response_body: string;
  response_headers: Record<string, string>;
  status_code: number;
  delay_ms: number;
  is_active: boolean;
  call_count: number;
  last_called_at: string | null;
  created_at: string;
  updated_at: string;
  serve_url_path: string;
}

export interface MockEndpointIn {
  code: string;
  name: string;
  description?: string | null;
  response_format: MockResponseFormat;
  response_body: string;
  response_headers?: Record<string, string>;
  status_code?: number;
  delay_ms?: number;
  is_active?: boolean;
}

const BASE = "/v2/mock-api/endpoints";

export function useMockEndpoints() {
  return useQuery({
    queryKey: ["v2-mock-api-endpoints"],
    queryFn: () => apiRequest<MockEndpoint[]>(BASE),
    refetchInterval: 30_000,
  });
}

export function useCreateMockEndpoint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: MockEndpointIn) =>
      apiRequest<MockEndpoint>(BASE, { method: "POST", body }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["v2-mock-api-endpoints"] }),
  });
}

export function useUpdateMockEndpoint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ mock_id, body }: { mock_id: number; body: MockEndpointIn }) =>
      apiRequest<MockEndpoint>(`${BASE}/${mock_id}`, { method: "PUT", body }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["v2-mock-api-endpoints"] }),
  });
}

export function useDeleteMockEndpoint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mock_id: number) =>
      apiRequest<void>(`${BASE}/${mock_id}`, { method: "DELETE" }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["v2-mock-api-endpoints"] }),
  });
}
