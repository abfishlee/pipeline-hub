// Phase 7 Wave 5/6 — Operations Dashboard + dispatch.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export interface OperationsSummary {
  workflow_count: number;
  runs_24h: number;
  success_24h: number;
  failed_24h: number;
  success_rate_pct: number;
  rows_ingested_24h: number;
  pending_replay: number;
  provider_failures_24h: number;
}

export interface ChannelStatus {
  workflow_id: number;
  workflow_name: string;
  status: string;
  schedule_cron: string | null;
  schedule_enabled: boolean;
  last_run_at: string | null;
  last_run_status: string | null;
  runs_24h: number;
  success_24h: number;
  failed_24h: number;
  rows_24h: number;
  success_rate_pct: number;
}

export interface NodeHeatmapCell {
  node_key: string;
  node_type: string;
  success_count: number;
  failed_count: number;
  skipped_count: number;
}

export interface FailureCategoryRow {
  category: string;
  failed_count: number;
  sample_error: string | null;
  sample_workflow_name: string | null;
  last_failed_at: string | null;
}

export function useFailureSummary() {
  return useQuery({
    queryKey: ["v2-operations-failure-summary"],
    queryFn: () => apiRequest<FailureCategoryRow[]>("/v2/operations/failure-summary"),
    refetchInterval: 30_000,
  });
}

export interface DispatchSummary {
  pending_before: number;
  dispatched: number;
  manual: number;
  failed: number;
  pending_after: number;
  items: Array<{
    envelope_id: number;
    channel_code: string;
    workflow_id: number | null;
    pipeline_run_id: number | null;
    status: string;
    error: string | null;
  }>;
}

export function useOperationsSummary() {
  return useQuery({
    queryKey: ["v2-operations-summary"],
    queryFn: () => apiRequest<OperationsSummary>("/v2/operations/summary"),
    refetchInterval: 30_000, // § 15.5 — 30s polling
  });
}

export function useOperationsChannels(limit = 50) {
  return useQuery({
    queryKey: ["v2-operations-channels", limit],
    queryFn: () =>
      apiRequest<ChannelStatus[]>("/v2/operations/channels", {
        params: { limit },
      }),
    refetchInterval: 30_000,
  });
}

export function useWorkflowHeatmap(workflowId: number | null, days = 7) {
  return useQuery({
    queryKey: ["v2-operations-heatmap", workflowId, days],
    enabled: workflowId != null,
    queryFn: () =>
      apiRequest<NodeHeatmapCell[]>(`/v2/operations/heatmap/${workflowId}`, {
        params: { days },
      }),
    refetchInterval: 30_000,
  });
}

export function useDispatchPending() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (limit: number = 50) =>
      apiRequest<DispatchSummary>("/v2/operations/dispatch-pending", {
        method: "POST",
        params: { limit },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["v2-operations-summary"] });
      qc.invalidateQueries({ queryKey: ["v2-operations-channels"] });
    },
  });
}
