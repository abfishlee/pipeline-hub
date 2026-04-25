import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

// ---------------------------------------------------------------------------
// 3.2.4 dry-run validate
// ---------------------------------------------------------------------------
export interface SqlValidateResponse {
  valid: boolean;
  error: string | null;
  referenced_tables: string[];
}

export function useValidateSql() {
  return useMutation({
    mutationFn: (sql: string) =>
      apiRequest<SqlValidateResponse>("/v1/sql-studio/validate", {
        method: "POST",
        body: { sql },
      }),
  });
}

// ---------------------------------------------------------------------------
// 3.2.5 preview / explain
// ---------------------------------------------------------------------------
export interface SqlPreviewRequest {
  sql: string;
  limit?: number;
  sql_query_version_id?: number | null;
}

export interface SqlPreviewResponse {
  columns: string[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
}

export function usePreviewSql() {
  return useMutation({
    mutationFn: (body: SqlPreviewRequest) =>
      apiRequest<SqlPreviewResponse>("/v1/sql-studio/preview", {
        method: "POST",
        body,
      }),
  });
}

export interface SqlExplainResponse {
  plan_json: Record<string, unknown>[];
  elapsed_ms: number;
}

export function useExplainSql() {
  return useMutation({
    mutationFn: (sql: string) =>
      apiRequest<SqlExplainResponse>("/v1/sql-studio/explain", {
        method: "POST",
        body: { sql },
      }),
  });
}

// ---------------------------------------------------------------------------
// 3.2.5 SqlQuery / SqlQueryVersion CRUD
// ---------------------------------------------------------------------------
export type SqlVersionStatus =
  | "DRAFT"
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "SUPERSEDED";

export interface SqlQueryVersionOut {
  sql_query_version_id: number;
  sql_query_id: number;
  version_no: number;
  sql_text: string;
  referenced_tables: string[];
  status: SqlVersionStatus;
  parent_version_id: number | null;
  submitted_by: number | null;
  submitted_at: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  review_comment: string | null;
  created_at: string;
}

export interface SqlQueryOut {
  sql_query_id: number;
  name: string;
  description: string | null;
  owner_user_id: number;
  current_version_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface SqlQueryDetail extends SqlQueryOut {
  versions: SqlQueryVersionOut[];
}

export function useSqlQueries() {
  return useQuery({
    queryKey: ["sql-studio", "queries"],
    queryFn: () =>
      apiRequest<SqlQueryOut[]>("/v1/sql-studio/queries", {
        params: { limit: 200 },
      }),
  });
}

export function useSqlQueryDetail(queryId: number | null) {
  return useQuery({
    queryKey: ["sql-studio", "queries", queryId],
    enabled: queryId != null,
    queryFn: () =>
      apiRequest<SqlQueryDetail>(`/v1/sql-studio/queries/${queryId}`),
  });
}

export function useCreateSqlQuery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      name: string;
      description?: string | null;
      sql_text: string;
    }) =>
      apiRequest<SqlQueryDetail>("/v1/sql-studio/queries", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries"] });
    },
  });
}

export function useAddSqlVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      queryId,
      sql_text,
    }: {
      queryId: number;
      sql_text: string;
    }) =>
      apiRequest<SqlQueryVersionOut>(
        `/v1/sql-studio/queries/${queryId}/versions`,
        { method: "POST", body: { sql_text } },
      ),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries", vars.queryId] });
    },
  });
}

export function useSubmitSqlVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: number) =>
      apiRequest<SqlQueryVersionOut>(
        `/v1/sql-studio/versions/${versionId}/submit`,
        { method: "POST" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries"] });
    },
  });
}

export function useApproveSqlVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      versionId,
      comment,
    }: {
      versionId: number;
      comment?: string | null;
    }) =>
      apiRequest<SqlQueryVersionOut>(
        `/v1/sql-studio/versions/${versionId}/approve`,
        { method: "POST", body: { comment: comment ?? null } },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries"] });
    },
  });
}

export function useRejectSqlVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      versionId,
      comment,
    }: {
      versionId: number;
      comment?: string | null;
    }) =>
      apiRequest<SqlQueryVersionOut>(
        `/v1/sql-studio/versions/${versionId}/reject`,
        { method: "POST", body: { comment: comment ?? null } },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries"] });
    },
  });
}
