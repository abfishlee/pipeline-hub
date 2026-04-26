// Phase 6 — domain registry client (dropdown 용).
import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../client";

export interface DomainDefinition {
  domain_code: string;
  name: string;
  description: string | null;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export function useDomains() {
  return useQuery({
    queryKey: ["v2-domains"],
    queryFn: () => apiRequest<DomainDefinition[]>("/v2/domains"),
  });
}
