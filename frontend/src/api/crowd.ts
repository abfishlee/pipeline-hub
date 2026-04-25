import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type CrowdTaskStatus = "PENDING" | "REVIEWING" | "APPROVED" | "REJECTED";

export const CROWD_REASONS = [
  "ocr_low_confidence",
  "std_low_confidence",
  "price_fact_low_confidence",
  "price_fact_sample_review",
] as const;
export type CrowdReason = (typeof CROWD_REASONS)[number];

export interface CrowdTask {
  crowd_task_id: number;
  raw_object_id: number;
  partition_date: string;
  ocr_result_id: number | null;
  reason: string;
  status: CrowdTaskStatus;
  payload_json: Record<string, unknown>;
  assigned_to: number | null;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: number | null;
}

export interface OcrResultPreview {
  ocr_result_id: number;
  page_no: number | null;
  text_content: string | null;
  confidence_score: number | null;
  engine_name: string;
}

export interface CrowdTaskDetail extends CrowdTask {
  raw_object_uri: string | null;
  raw_object_payload: Record<string, unknown> | null;
  ocr_results: OcrResultPreview[];
}

export interface ListCrowdTasksParams {
  status?: CrowdTaskStatus;
  reason?: string;
  limit?: number;
  offset?: number;
}

export function useCrowdTasks(params: ListCrowdTasksParams = {}) {
  return useQuery({
    queryKey: ["crowd-tasks", params],
    queryFn: () =>
      apiRequest<CrowdTask[]>("/v1/crowd-tasks", { params: { ...params } }),
  });
}

export function useCrowdTaskDetail(crowdTaskId: number | null) {
  return useQuery({
    queryKey: ["crowd-tasks", crowdTaskId],
    enabled: crowdTaskId != null,
    queryFn: () =>
      apiRequest<CrowdTaskDetail>(`/v1/crowd-tasks/${crowdTaskId}`),
  });
}

export function useUpdateCrowdTaskStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      crowdTaskId,
      status,
      note,
    }: {
      crowdTaskId: number;
      status: "REVIEWING" | "APPROVED" | "REJECTED";
      note?: string;
    }) =>
      apiRequest<CrowdTask>(`/v1/crowd-tasks/${crowdTaskId}/status`, {
        method: "PATCH",
        body: { status, note },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["crowd-tasks"] });
    },
  });
}
