import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

export interface MergeCandidateProduct {
  product_id: number;
  canonical_name: string;
  grade: string | null;
  package_type: string | null;
  sale_unit_norm: string | null;
  weight_g: number | null;
  confidence_score: number | null;
}

export interface MergeCandidateOut {
  std_code: string;
  cluster_size: number;
  products: MergeCandidateProduct[];
}

export interface MergeOpOut {
  merge_op_id: number;
  source_product_ids: number[];
  target_product_id: number;
  merged_at: string;
  merged_by: number | null;
  reason: string | null;
  is_unmerged: boolean;
  unmerged_at: string | null;
  unmerged_by: number | null;
  mapping_count: number | null;
}

export interface RunSummary {
  candidates: number;
  merged: number;
  disputed: number;
}

export interface UnmergeResponse {
  merge_op_id: number;
  new_product_ids: number[];
}

export function useMergeCandidates(stdCode: string | null) {
  return useQuery({
    queryKey: ["master-merge", "candidates", stdCode],
    queryFn: () =>
      apiRequest<MergeCandidateOut[]>("/v1/admin/master-merge/candidates", {
        params: { std_code: stdCode ?? undefined },
      }),
  });
}

export function useMergeOps(onlyActive = true) {
  return useQuery({
    queryKey: ["master-merge", "ops", onlyActive],
    queryFn: () =>
      apiRequest<MergeOpOut[]>("/v1/admin/master-merge/ops", {
        params: { only_active: onlyActive, limit: 100 },
      }),
  });
}

export function useRunAutoMerge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (stdCode: string | null) =>
      apiRequest<RunSummary>("/v1/admin/master-merge/run", {
        method: "POST",
        params: { std_code: stdCode ?? undefined },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["master-merge"] }),
  });
}

export function useUnmerge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mergeOpId: number) =>
      apiRequest<UnmergeResponse>(
        `/v1/admin/master-merge/ops/${mergeOpId}/unmerge`,
        { method: "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["master-merge"] }),
  });
}
