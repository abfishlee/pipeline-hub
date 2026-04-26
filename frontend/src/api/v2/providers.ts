// Phase 6 Wave 2B — provider catalog client (read-only for Transform Designer).
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../client";

export interface ProviderDefinition {
  provider_code: string;
  provider_kind: string;
  implementation_type: string;
  config_schema: Record<string, unknown>;
  secret_ref: string | null;
  description: string | null;
  is_active: boolean;
  created_at: string;
}

export function useProviders(provider_kind?: string) {
  return useQuery({
    queryKey: ["v2-providers", provider_kind ?? null],
    queryFn: () =>
      apiRequest<ProviderDefinition[]>("/v2/providers", {
        params: provider_kind ? { provider_kind } : undefined,
      }),
  });
}
