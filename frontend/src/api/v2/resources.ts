// Phase 6 Wave 3 — resource_definition list-light client (dropdown 보조).
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../client";

export interface ResourceLight {
  resource_id: number;
  domain_code: string;
  resource_code: string;
  canonical_table: string | null;
  fact_table: string | null;
  standard_code_namespace: string | null;
  status: string;
  version: number;
  created_at: string;
}

export interface ListResourcesParams {
  domain_code?: string;
  status?: string;
}

export function useResources(params: ListResourcesParams = {}) {
  return useQuery({
    queryKey: ["v2-resources", params],
    queryFn: () =>
      apiRequest<ResourceLight[]>("/v2/resources", { params: { ...params } }),
  });
}
