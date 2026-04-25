import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type JobStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCESS"
  | "FAILED"
  | "CANCELLED";

export type JobType = "ON_DEMAND" | "SCHEDULED" | "RETRY" | "BACKFILL";

export interface Job {
  job_id: number;
  source_id: number;
  job_type: JobType;
  status: JobStatus;
  requested_by: number | null;
  parameters: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
  input_count: number;
  output_count: number;
  error_count: number;
  error_message: string | null;
  created_at: string;
}

export interface ListJobsParams {
  source_id?: number;
  status?: JobStatus;
  job_type?: JobType;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

export function useJobs(params: ListJobsParams = {}) {
  return useQuery({
    queryKey: ["jobs", params],
    queryFn: () => apiRequest<Job[]>("/v1/jobs", { params: { ...params } }),
  });
}

export function useJob(jobId: number | null) {
  return useQuery({
    queryKey: ["jobs", jobId],
    enabled: jobId != null,
    queryFn: () => apiRequest<Job>(`/v1/jobs/${jobId}`),
  });
}
