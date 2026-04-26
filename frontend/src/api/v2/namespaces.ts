// Phase 6 Wave 6 — Standard Code Namespace client.
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../client";

export interface Namespace {
  namespace_id: number;
  domain_code: string;
  name: string;
  description: string | null;
  std_code_table: string | null;
  created_at: string;
}

export interface StdCodeRow {
  std_code: string;
  display_name: string | null;
  description: string | null;
  sort_order: number | null;
}

export function useNamespaces(domainCode?: string) {
  return useQuery({
    queryKey: ["v2-namespaces", domainCode ?? null],
    queryFn: () =>
      apiRequest<Namespace[]>("/v2/namespaces", {
        params: domainCode ? { domain_code: domainCode } : undefined,
      }),
  });
}

export function useNamespaceCodes(namespaceId: number | null, limit = 200) {
  return useQuery({
    queryKey: ["v2-namespace-codes", namespaceId, limit],
    enabled: namespaceId != null,
    queryFn: () =>
      apiRequest<StdCodeRow[]>(`/v2/namespaces/${namespaceId}/codes`, {
        params: { limit },
      }),
  });
}
