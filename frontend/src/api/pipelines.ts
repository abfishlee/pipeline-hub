import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type WorkflowStatus = "DRAFT" | "PUBLISHED" | "ARCHIVED";
export type NodeType =
  | "NOOP"
  | "SOURCE_API"
  | "SQL_TRANSFORM"
  | "DEDUP"
  | "DQ_CHECK"
  | "LOAD_MASTER"
  | "NOTIFY";

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
