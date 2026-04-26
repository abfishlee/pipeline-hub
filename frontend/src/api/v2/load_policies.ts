// Phase 6 Wave 3 — Load Policy client.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export type LoadPolicyStatus = "DRAFT" | "REVIEW" | "APPROVED" | "PUBLISHED";
export type LoadPolicyMode =
  | "append_only"
  | "upsert"
  | "scd_type_2"
  | "current_snapshot";

export interface LoadPolicy {
  policy_id: number;
  resource_id: number;
  mode: LoadPolicyMode;
  key_columns: string[];
  partition_expr: string | null;
  scd_options_json: Record<string, unknown>;
  chunk_size: number;
  statement_timeout_ms: number;
  status: LoadPolicyStatus;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface LoadPolicyIn {
  resource_id: number;
  mode: LoadPolicyMode;
  key_columns?: string[];
  partition_expr?: string | null;
  scd_options_json?: Record<string, unknown>;
  chunk_size?: number;
  statement_timeout_ms?: number;
  version?: number;
}

export interface LoadPolicyUpdate {
  mode?: LoadPolicyMode;
  key_columns?: string[];
  partition_expr?: string | null;
  scd_options_json?: Record<string, unknown>;
  chunk_size?: number;
  statement_timeout_ms?: number;
}

export interface LoadTargetDryRunRequest {
  domain_code: string;
  source_table: string;
  policy_id?: number | null;
  resource_id?: number | null;
  target_table?: string | null;
}

const BASE = "/v2/load-policies";

export interface ListLoadPoliciesParams {
  resource_id?: number;
  status?: LoadPolicyStatus;
  mode?: LoadPolicyMode;
}

export function useLoadPolicies(params: ListLoadPoliciesParams = {}) {
  return useQuery({
    queryKey: ["v2-load-policies", params],
    queryFn: () => apiRequest<LoadPolicy[]>(BASE, { params: { ...params } }),
  });
}

export function useCreateLoadPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: LoadPolicyIn) =>
      apiRequest<LoadPolicy>(BASE, { method: "POST", body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-load-policies"] }),
  });
}

export function useUpdateLoadPolicy(policyId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: LoadPolicyUpdate) =>
      apiRequest<LoadPolicy>(`${BASE}/${policyId}`, {
        method: "PATCH",
        body: req,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-load-policies"] }),
  });
}

export function useDeleteLoadPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (policyId: number) =>
      apiRequest<void>(`${BASE}/${policyId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-load-policies"] }),
  });
}

export function useTransitionLoadPolicy(policyId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target_status: LoadPolicyStatus) =>
      apiRequest<LoadPolicy>(`${BASE}/${policyId}/transition`, {
        method: "POST",
        body: { target_status },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-load-policies"] }),
  });
}

export function useDryRunLoadTarget() {
  return useMutation({
    mutationFn: (req: LoadTargetDryRunRequest) =>
      apiRequest<{
        dry_run_id: number | null;
        kind: string;
        rows_affected: number[];
        row_counts: number[];
        errors: string[];
        target_summary: Record<string, unknown>;
      }>("/v2/dryrun/load-target", { method: "POST", body: req }),
  });
}
