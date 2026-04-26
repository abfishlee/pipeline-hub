// Phase 6 Wave 6 — DQ Rule client.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export type DqStatus = "DRAFT" | "REVIEW" | "APPROVED" | "PUBLISHED";
export type DqSeverity = "INFO" | "WARN" | "ERROR" | "BLOCK";
export type DqRuleKind =
  | "row_count_min"
  | "null_pct_max"
  | "unique_columns"
  | "reference"
  | "range"
  | "custom_sql"
  // Phase 7 Wave 4 추가
  | "freshness"
  | "anomaly_zscore"
  | "drift";

export interface DqRule {
  rule_id: number;
  domain_code: string;
  target_table: string;
  rule_kind: DqRuleKind;
  rule_json: Record<string, unknown>;
  severity: DqSeverity;
  timeout_ms: number;
  sample_limit: number;
  max_scan_rows: number | null;
  incremental_only: boolean;
  status: DqStatus;
  version: number;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface DqRuleCreate {
  domain_code: string;
  target_table: string;
  rule_kind: DqRuleKind;
  rule_json?: Record<string, unknown>;
  severity?: DqSeverity;
  timeout_ms?: number;
  sample_limit?: number;
  max_scan_rows?: number | null;
  incremental_only?: boolean;
  description?: string | null;
}

export interface DqRuleUpdate {
  rule_json?: Record<string, unknown>;
  severity?: DqSeverity;
  timeout_ms?: number;
  sample_limit?: number;
  max_scan_rows?: number | null;
  incremental_only?: boolean;
  description?: string | null;
  status?: DqStatus;
}

export interface CustomSqlPreviewRequest {
  domain_code: string;
  sql: string;
  sample_limit?: number;
}

export interface CustomSqlPreviewResponse {
  is_valid: boolean;
  error: string | null;
  row_count: number | null;
  duration_ms: number;
}

const BASE = "/v2/dq-rules";

export interface ListDqRulesParams {
  domain_code?: string;
  target_table?: string;
}

export function useDqRules(params: ListDqRulesParams = {}) {
  return useQuery({
    queryKey: ["v2-dq-rules", params],
    queryFn: () => apiRequest<DqRule[]>(BASE, { params: { ...params } }),
  });
}

export function useCreateDqRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: DqRuleCreate) =>
      apiRequest<DqRule>(BASE, { method: "POST", body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-dq-rules"] }),
  });
}

export function useUpdateDqRule(ruleId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: DqRuleUpdate) =>
      apiRequest<DqRule>(`${BASE}/${ruleId}`, { method: "PATCH", body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-dq-rules"] }),
  });
}

export function usePreviewCustomSql() {
  return useMutation({
    mutationFn: (req: CustomSqlPreviewRequest) =>
      apiRequest<CustomSqlPreviewResponse>(`${BASE}/preview`, {
        method: "POST",
        body: req,
      }),
  });
}
