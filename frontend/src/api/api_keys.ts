import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type PublicApiScope = "prices.read" | "products.read" | "aggregates.read";

export interface ApiKeyOut {
  api_key_id: number;
  key_prefix: string;
  client_name: string;
  scope: string[];
  retailer_allowlist: number[];
  rate_limit_per_min: number;
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreate {
  client_name: string;
  scope: PublicApiScope[];
  retailer_allowlist: number[];
  rate_limit_per_min: number;
  expires_at?: string | null;
}

export interface ApiKeyCreated extends ApiKeyOut {
  secret: string; // `<prefix>.<full>` — 1회 노출
}

export function useApiKeys() {
  return useQuery({
    queryKey: ["api-keys"],
    queryFn: () => apiRequest<ApiKeyOut[]>("/v1/api-keys"),
  });
}

export function useCreateApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ApiKeyCreate) =>
      apiRequest<ApiKeyCreated>("/v1/api-keys", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });
}

export function useRevokeApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (apiKeyId: number) =>
      apiRequest<void>(`/v1/api-keys/${apiKeyId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });
}
