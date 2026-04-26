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
      qc.invalidateQueries({ queryKey: ["crowd-v4"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Phase 4.2.1 정식 API (/v1/crowd/tasks)
// ---------------------------------------------------------------------------
export type TaskKind =
  | "OCR_REVIEW"
  | "PRODUCT_MATCHING"
  | "RECEIPT_VALIDATION"
  | "ANOMALY_CHECK"
  | "std_low_confidence"
  | "ocr_low_confidence"
  | "price_fact_low_confidence"
  | "sample_review";

export type TaskStatus =
  | "PENDING"
  | "REVIEWING"
  | "CONFLICT"
  | "APPROVED"
  | "REJECTED"
  | "CANCELLED";

export type ReviewDecision = "APPROVE" | "REJECT" | "SKIP";
export type ConsensusKind = "SINGLE" | "DOUBLE_AGREED" | "CONFLICT_RESOLVED";

export interface TaskV4 {
  crowd_task_id: number;
  task_kind: TaskKind;
  priority: number;
  raw_object_id: number | null;
  partition_date: string | null;
  ocr_result_id: number | null;
  std_record_id: number | null;
  payload: Record<string, unknown>;
  status: TaskStatus;
  requires_double_review: boolean;
  created_at: string;
  updated_at: string;
}

export interface TaskAssignmentV4 {
  assignment_id: number;
  crowd_task_id: number;
  reviewer_id: number;
  assigned_at: string;
  due_at: string | null;
  released_at: string | null;
}

export interface ReviewV4 {
  review_id: number;
  crowd_task_id: number;
  reviewer_id: number;
  decision: ReviewDecision;
  decision_payload: Record<string, unknown>;
  comment: string | null;
  time_spent_ms: number | null;
  decided_at: string;
}

export interface TaskDecisionV4 {
  crowd_task_id: number;
  final_decision: "APPROVE" | "REJECT";
  decided_by: number | null;
  consensus_kind: ConsensusKind;
  effect_payload: Record<string, unknown>;
  decided_at: string;
}

export interface TaskFullDetail extends TaskV4 {
  assignments: TaskAssignmentV4[];
  reviews: ReviewV4[];
  decision: TaskDecisionV4 | null;
}

export interface ReviewerStat {
  reviewer_id: number;
  display_name: string;
  count_30d: number;
  avg_decision_ms: number | null;
}

export function useCrowdTasksV4(params: {
  status?: TaskStatus;
  task_kind?: TaskKind;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["crowd-v4", "tasks", params],
    queryFn: () =>
      apiRequest<TaskV4[]>("/v1/crowd/tasks", { params: { ...params } }),
  });
}

export function useCrowdTaskDetailV4(taskId: number | null) {
  return useQuery({
    queryKey: ["crowd-v4", "tasks", taskId],
    enabled: taskId != null,
    queryFn: () =>
      apiRequest<TaskFullDetail>(`/v1/crowd/tasks/${taskId}`),
  });
}

export function useAssignReviewers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      reviewer_ids,
      due_at,
    }: {
      taskId: number;
      reviewer_ids: number[];
      due_at?: string | null;
    }) =>
      apiRequest<TaskAssignmentV4[]>(
        `/v1/crowd/tasks/${taskId}/assign`,
        { method: "POST", body: { reviewer_ids, due_at: due_at ?? null } },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crowd-v4"] }),
  });
}

export function useSubmitReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      decision,
      decision_payload,
      comment,
      time_spent_ms,
    }: {
      taskId: number;
      decision: ReviewDecision;
      decision_payload?: Record<string, unknown>;
      comment?: string | null;
      time_spent_ms?: number | null;
    }) =>
      apiRequest<ReviewV4>(`/v1/crowd/tasks/${taskId}/review`, {
        method: "POST",
        body: {
          decision,
          decision_payload: decision_payload ?? {},
          comment: comment ?? null,
          time_spent_ms: time_spent_ms ?? null,
        },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crowd-v4"] }),
  });
}

export function useResolveConflict() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      taskId,
      final_decision,
      note,
    }: {
      taskId: number;
      final_decision: "APPROVE" | "REJECT";
      note?: string | null;
    }) =>
      apiRequest<TaskDecisionV4>(`/v1/crowd/tasks/${taskId}/resolve`, {
        method: "POST",
        body: { final_decision, note: note ?? null },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["crowd-v4"] }),
  });
}

export function useReviewerStats() {
  return useQuery({
    queryKey: ["crowd-v4", "stats", "reviewers"],
    queryFn: () => apiRequest<ReviewerStat[]>("/v1/crowd/stats/reviewers"),
    staleTime: 30_000,
  });
}
