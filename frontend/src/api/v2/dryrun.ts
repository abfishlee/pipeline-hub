// Phase 6 Wave 5 — Dry-run client (workflow-level + recent + checklist).
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiRequest } from "../client";

export interface NodeDryRunResult {
  node_id: number;
  node_key: string;
  node_type: string;
  status: "success" | "failed" | "skipped";
  row_count: number;
  duration_ms: number;
  error_message: string | null;
  output_table: string | null;
  payload: Record<string, unknown>;
}

export interface WorkflowDryRunResponse {
  workflow_id: number;
  name: string;
  domain_code: string | null;
  status: "success" | "failed";
  total_duration_ms: number;
  succeeded: number;
  failed: number;
  skipped: number;
  nodes: NodeDryRunResult[];
}

export interface DryRunRecord {
  dry_run_id: number;
  requested_by: number | null;
  kind: string;
  domain_code: string | null;
  target_summary: Record<string, unknown>;
  row_counts: Record<string, unknown>;
  errors: string[];
  duration_ms: number;
  requested_at: string;
}

export function useDryRunWorkflow() {
  return useMutation({
    mutationFn: (workflowId: number) =>
      apiRequest<WorkflowDryRunResponse>(`/v2/dryrun/workflow/${workflowId}`, {
        method: "POST",
      }),
  });
}

export interface ListRecentParams {
  kind?: string;
  domain_code?: string;
  limit?: number;
}

export function useRecentDryRuns(params: ListRecentParams = {}) {
  return useQuery({
    queryKey: ["v2-dryrun-recent", params],
    queryFn: () =>
      apiRequest<DryRunRecord[]>("/v2/dryrun/recent", { params: { ...params } }),
  });
}

// ---------------------------------------------------------------------------
// Mini Publish Checklist
// ---------------------------------------------------------------------------
export type EntityType =
  | "source_contract"
  | "field_mapping"
  | "dq_rule"
  | "mart_load_policy"
  | "sql_asset"
  | "load_policy";

export interface ChecklistRunRequest {
  entity_type: EntityType;
  entity_id: number;
  entity_version?: number;
  domain_code?: string | null;
  current_status?: string | null;
  target_table?: string | null;
  contract_id?: number | null;
}

export interface CheckEntry {
  code: string;
  passed: boolean;
  detail: string | null;
  metadata: Record<string, unknown>;
}

export interface ChecklistOut {
  checklist_id: number | null;
  entity_type: string;
  entity_id: number;
  entity_version: number;
  domain_code: string | null;
  all_passed: boolean;
  failed_check_codes: string[];
  checks: CheckEntry[];
  requested_at: string;
}

export function useRunChecklist() {
  return useMutation({
    mutationFn: (req: ChecklistRunRequest) =>
      apiRequest<ChecklistOut>("/v2/checklist/run", {
        method: "POST",
        body: req,
      }),
  });
}

export function useRecentChecklists(params: {
  entity_type?: EntityType;
  domain_code?: string;
  limit?: number;
} = {}) {
  return useQuery({
    queryKey: ["v2-checklist-recent", params],
    queryFn: () =>
      apiRequest<ChecklistOut[]>("/v2/checklist/recent", {
        params: { ...params },
      }),
  });
}
