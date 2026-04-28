// Phase 6 — domain registry client (dropdown 용).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export interface DomainCreate {
  domain_code: string;
  name: string;
  description?: string | null;
}

export function useCreateDomain() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DomainCreate) =>
      apiRequest<DomainDefinition>("/v2/domains", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-domains"] }),
  });
}
