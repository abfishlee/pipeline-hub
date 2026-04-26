import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type WorkflowStatus = "DRAFT" | "PUBLISHED" | "ARCHIVED";
export type NodeType =
  // v1 (Phase 3.2)
  | "NOOP"
  | "SOURCE_API"
  | "SQL_TRANSFORM"
  | "DEDUP"
  | "DQ_CHECK"
  | "LOAD_MASTER"
  | "NOTIFY"
  // v2 (Phase 5 generic + Phase 6 Wave 1)
  | "MAP_FIELDS"
  | "SQL_INLINE_TRANSFORM"
  | "SQL_ASSET_TRANSFORM"
  | "HTTP_TRANSFORM"
  | "FUNCTION_TRANSFORM"
  | "LOAD_TARGET"
  | "OCR_TRANSFORM"
  | "CRAWL_FETCH"
  | "STANDARDIZE"
  | "SOURCE_DATA"
  | "PUBLIC_API_FETCH"
  // Phase 7 Wave 1A — 외부 push / upload / DB 수집
  | "WEBHOOK_INGEST"
  | "FILE_UPLOAD_INGEST"
  | "DB_INCREMENTAL_FETCH"
  // Phase 7 Wave 1B — OCR/Crawler push 결과
  | "OCR_RESULT_INGEST"
  | "CRAWLER_RESULT_INGEST"
  | "CDC_EVENT_FETCH";

export interface NodeOut {
  node_id: number;
  node_key: string;
  node_type: NodeType;
  config_json: Record<string, unknown>;
  position_x: number;
  position_y: number;
}

export interface EdgeOut {
  edge_id: number;
  from_node_id: number;
  to_node_id: number;
  condition_expr: Record<string, unknown> | null;
}

export interface WorkflowOut {
  workflow_id: number;
  name: string;
  version: number;
  description: string | null;
  status: WorkflowStatus;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  // Phase 3.2.7
  schedule_cron: string | null;
  schedule_enabled: boolean;
}

export interface WorkflowDetail extends WorkflowOut {
  nodes: NodeOut[];
  edges: EdgeOut[];
}

export type NodeRunStatus =
  | "PENDING"
  | "READY"
  | "RUNNING"
  | "SUCCESS"
  | "FAILED"
  | "SKIPPED"
  | "CANCELLED";

export type PipelineRunStatus =
  | "PENDING"
  | "RUNNING"
  | "ON_HOLD"
  | "SUCCESS"
  | "FAILED"
  | "CANCELLED";

export interface NodeRunOut {
  node_run_id: number;
  node_definition_id: number;
  node_key: string;
  node_type: string;
  status: NodeRunStatus;
  attempt_no: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  output_json: Record<string, unknown> | null;
}

export interface PipelineRunOut {
  pipeline_run_id: number;
  workflow_id: number;
  run_date: string;
  status: PipelineRunStatus;
  triggered_by: number | null;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface PipelineRunDetail extends PipelineRunOut {
  node_runs: NodeRunOut[];
}

export function useWorkflows(params: { status?: WorkflowStatus; limit?: number } = {}) {
  return useQuery({
    queryKey: ["pipelines", "workflows", params],
    queryFn: () =>
      apiRequest<WorkflowOut[]>("/v1/pipelines", { params: { ...params } }),
  });
}

export function useWorkflowDetail(workflowId: number | null) {
  return useQuery({
    queryKey: ["pipelines", "workflows", workflowId],
    enabled: workflowId != null,
    queryFn: () =>
      apiRequest<WorkflowDetail>(`/v1/pipelines/${workflowId}`),
  });
}

export function usePipelineRun(pipelineRunId: number | null) {
  return useQuery({
    queryKey: ["pipelines", "runs", pipelineRunId],
    enabled: pipelineRunId != null,
    queryFn: () =>
      apiRequest<PipelineRunDetail>(`/v1/pipelines/runs/${pipelineRunId}`),
    refetchInterval: 5_000, // SSE 가 끊겨도 5s 폴링으로 fallback.
  });
}

// ---------------------------------------------------------------------------
// Designer mutations (Phase 3.2.4)
// ---------------------------------------------------------------------------
export interface NodeIn {
  node_key: string;
  node_type: NodeType;
  config_json?: Record<string, unknown>;
  position_x?: number;
  position_y?: number;
}

export interface EdgeIn {
  from_node_key: string;
  to_node_key: string;
  condition_expr?: Record<string, unknown> | null;
}

export interface WorkflowCreate {
  name: string;
  version?: number;
  description?: string | null;
  nodes: NodeIn[];
  edges?: EdgeIn[];
}

export interface WorkflowPatch {
  name?: string;
  description?: string | null;
  nodes?: NodeIn[];
  edges?: EdgeIn[];
}

export function useCreateWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: WorkflowCreate) =>
      apiRequest<WorkflowDetail>("/v1/pipelines", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines", "workflows"] });
    },
  });
}

export function useUpdateWorkflow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      workflowId,
      body,
    }: {
      workflowId: number;
      body: WorkflowPatch;
    }) =>
      apiRequest<WorkflowDetail>(`/v1/pipelines/${workflowId}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({
        queryKey: ["pipelines", "workflows", vars.workflowId],
      });
      qc.invalidateQueries({ queryKey: ["pipelines", "workflows"] });
    },
  });
}

// Phase 3.2.6: 응답이 단순 WorkflowOut 이 아니라 transition 메타로 확장됨.
export interface PipelineReleaseOut {
  release_id: number;
  workflow_name: string;
  version_no: number;
  source_workflow_id: number | null;
  released_workflow_id: number;
  released_by: number | null;
  released_at: string;
  change_summary: {
    added?: string[];
    removed?: string[];
    changed?: string[];
    edges_added?: string[];
    edges_removed?: string[];
  };
}

export interface PipelineReleaseDetail extends PipelineReleaseOut {
  nodes_snapshot: Array<Record<string, unknown>>;
  edges_snapshot: Array<Record<string, unknown>>;
}

export interface WorkflowStatusTransitionOut {
  workflow: WorkflowOut;
  published_workflow: WorkflowOut | null;
  release: PipelineReleaseOut | null;
}

export function useTransitionWorkflowStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      workflowId,
      status,
    }: {
      workflowId: number;
      status: "PUBLISHED" | "ARCHIVED";
    }) =>
      apiRequest<WorkflowStatusTransitionOut>(
        `/v1/pipelines/${workflowId}/status`,
        { method: "PATCH", body: { status } },
      ),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({
        queryKey: ["pipelines", "workflows", vars.workflowId],
      });
      qc.invalidateQueries({ queryKey: ["pipelines", "workflows"] });
      qc.invalidateQueries({ queryKey: ["pipelines", "releases"] });
    },
  });
}

export function usePipelineReleases(name?: string | null) {
  return useQuery({
    queryKey: ["pipelines", "releases", name ?? null],
    queryFn: () =>
      apiRequest<PipelineReleaseOut[]>("/v1/pipelines/releases", {
        params: { name: name ?? undefined, limit: 200 },
      }),
  });
}

export function usePipelineReleaseDetail(releaseId: number | null) {
  return useQuery({
    queryKey: ["pipelines", "releases", "detail", releaseId],
    enabled: releaseId != null,
    queryFn: () =>
      apiRequest<PipelineReleaseDetail>(`/v1/pipelines/releases/${releaseId}`),
  });
}

export interface NodeChangeOut {
  node_key: string;
  node_type: string | null;
  config_before: Record<string, unknown> | null;
  config_after: Record<string, unknown> | null;
}
export interface EdgeChangeOut {
  from_node_key: string;
  to_node_key: string;
}
export interface WorkflowDiffOut {
  before_workflow_id: number;
  after_workflow_id: number;
  nodes_added: NodeChangeOut[];
  nodes_removed: NodeChangeOut[];
  nodes_changed: NodeChangeOut[];
  edges_added: EdgeChangeOut[];
  edges_removed: EdgeChangeOut[];
}

export function useWorkflowDiff(
  workflowId: number | null,
  againstId: number | null,
) {
  return useQuery({
    queryKey: ["pipelines", "diff", workflowId, againstId],
    enabled: workflowId != null && againstId != null,
    queryFn: () =>
      apiRequest<WorkflowDiffOut>(`/v1/pipelines/${workflowId}/diff`, {
        params: { against: againstId! },
      }),
  });
}

export function useTriggerRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (workflowId: number) =>
      apiRequest<PipelineRunDetail>(`/v1/pipelines/${workflowId}/runs`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines", "runs"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Schedule / Backfill / Restart / Search (Phase 3.2.7)
// ---------------------------------------------------------------------------
export function useUpdateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      workflowId,
      cron,
      enabled,
    }: {
      workflowId: number;
      cron: string | null;
      enabled: boolean;
    }) =>
      apiRequest<WorkflowOut>(`/v1/pipelines/${workflowId}/schedule`, {
        method: "PATCH",
        body: { cron, enabled },
      }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({
        queryKey: ["pipelines", "workflows", vars.workflowId],
      });
      qc.invalidateQueries({ queryKey: ["pipelines", "workflows"] });
    },
  });
}

export interface BackfillResponse {
  pipeline_run_ids: number[];
  run_dates: string[];
}

export function useBackfill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      workflowId,
      start_date,
      end_date,
    }: {
      workflowId: number;
      start_date: string;
      end_date: string;
    }) =>
      apiRequest<BackfillResponse>(`/v1/pipelines/${workflowId}/backfill`, {
        method: "POST",
        body: { start_date, end_date },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines", "runs"] });
    },
  });
}

export interface RunSearchParams {
  workflow_id?: number | null;
  status?: PipelineRunStatus | null;
  from?: string | null; // YYYY-MM-DD
  to?: string | null;
  limit?: number;
  offset?: number;
}

export function useSearchRuns(params: RunSearchParams = {}) {
  return useQuery({
    queryKey: ["pipelines", "runs", "search", params],
    queryFn: () =>
      apiRequest<PipelineRunOut[]>("/v1/pipelines/runs", {
        params: {
          workflow_id: params.workflow_id ?? undefined,
          status: params.status ?? undefined,
          from: params.from ?? undefined,
          to: params.to ?? undefined,
          limit: params.limit ?? 100,
          offset: params.offset ?? 0,
        },
      }),
  });
}

export interface RestartResponse {
  new_pipeline_run_id: number;
  new_run_date: string;
  ready_node_run_ids: number[];
  seeded_success_node_keys: string[];
}

export function useRestartRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      from_node_key,
    }: {
      runId: number;
      from_node_key?: string | null;
    }) =>
      apiRequest<RestartResponse>(`/v1/pipelines/runs/${runId}/restart`, {
        method: "POST",
        body: { from_node_key: from_node_key ?? null },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines", "runs"] });
    },
  });
}

// ---------------------------------------------------------------------------
// DQ Gate (Phase 4.2.2) — ON_HOLD list + approve/reject.
// ---------------------------------------------------------------------------
export interface QualityResultOut {
  quality_result_id: number;
  pipeline_run_id: number | null;
  node_run_id: number | null;
  target_table: string;
  check_kind: string;
  passed: boolean;
  severity: string;
  status: "PASS" | "WARN" | "FAIL";
  details_json: Record<string, unknown>;
  sample_json: Array<Record<string, unknown>>;
  created_at: string;
}

export interface OnHoldRunOut extends PipelineRunOut {
  failed_node_keys: string[];
  quality_results: QualityResultOut[];
}

export interface HoldDecisionResponse {
  decision_id: number;
  pipeline_run_id: number;
  run_date: string;
  decision: "APPROVE" | "REJECT";
  pipeline_status: string;
  ready_node_run_ids: number[];
  cancelled_node_run_ids: number[];
  rollback_rows: number;
}

export function useOnHoldRuns(params: { limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: ["pipelines", "runs", "on_hold", params],
    queryFn: () =>
      apiRequest<OnHoldRunOut[]>("/v1/pipelines/runs/on_hold", {
        params: { limit: params.limit ?? 50, offset: params.offset ?? 0 },
      }),
    refetchInterval: 10_000,
  });
}

export function useApproveHold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      reason,
    }: {
      runId: number;
      reason?: string | null;
    }) =>
      apiRequest<HoldDecisionResponse>(
        `/v1/pipelines/runs/${runId}/hold/approve`,
        { method: "POST", body: { reason: reason ?? null } },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines", "runs"] });
    },
  });
}

export function useRejectHold() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      reason,
    }: {
      runId: number;
      reason?: string | null;
    }) =>
      apiRequest<HoldDecisionResponse>(
        `/v1/pipelines/runs/${runId}/hold/reject`,
        { method: "POST", body: { reason: reason ?? null } },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pipelines", "runs"] });
    },
  });
}
