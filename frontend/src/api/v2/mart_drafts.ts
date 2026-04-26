// Phase 6 Wave 3 — Mart draft + dryrun client.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export type MartStatus =
  | "DRAFT"
  | "REVIEW"
  | "APPROVED"
  | "PUBLISHED"
  | "ROLLED_BACK";

export interface MartDraft {
  draft_id: number;
  domain_code: string;
  target_table: string;
  ddl_text: string;
  diff_summary: Record<string, unknown>;
  status: MartStatus;
  applied_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MartColumnSpec {
  name: string;
  type: string;
  nullable?: boolean;
  default?: string | null;
  description?: string | null;
}

export interface MartIndexSpec {
  name: string;
  columns: string[];
  unique?: boolean;
}

export interface MartDesignerDryRunRequest {
  domain_code: string;
  target_table: string;
  columns: MartColumnSpec[];
  primary_key?: string[];
  partition_key?: string | null;
  indexes?: MartIndexSpec[];
  description?: string | null;
  save_as_draft?: boolean;
}

export interface MartDesignerDryRunResponse {
  dry_run_id: number | null;
  kind: string;
  domain_code: string | null;
  target_summary: Record<string, unknown>;
  ddl_text: string;
  is_alter: boolean;
  draft_id: number | null;
}

const BASE = "/v2/mart-drafts";

export interface ListMartDraftsParams {
  domain_code?: string;
  status?: MartStatus;
  target_table?: string;
}

export function useMartDrafts(params: ListMartDraftsParams = {}) {
  return useQuery({
    queryKey: ["v2-mart-drafts", params],
    queryFn: () => apiRequest<MartDraft[]>(BASE, { params: { ...params } }),
  });
}

export function useDeleteMartDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draftId: number) =>
      apiRequest<void>(`${BASE}/${draftId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-mart-drafts"] }),
  });
}

export function useTransitionMartDraft(draftId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target_status: MartStatus) =>
      apiRequest<MartDraft>(`${BASE}/${draftId}/transition`, {
        method: "POST",
        body: { target_status },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-mart-drafts"] }),
  });
}

export function useDryRunMartDesigner() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: MartDesignerDryRunRequest) =>
      apiRequest<MartDesignerDryRunResponse>("/v2/dryrun/mart-designer", {
        method: "POST",
        body: req,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-mart-drafts"] }),
  });
}
