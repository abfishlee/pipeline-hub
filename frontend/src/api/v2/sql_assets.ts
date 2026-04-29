// Phase 6 Wave 2B — SQL Asset Designer client.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export type AssetStatus = "DRAFT" | "REVIEW" | "APPROVED" | "PUBLISHED";
export type SqlAssetType =
  | "TRANSFORM_SQL"
  | "STANDARDIZATION_SQL"
  | "QUALITY_CHECK_SQL"
  | "DML_SCRIPT"
  | "FUNCTION"
  | "PROCEDURE"
  | "PYTHON_SCRIPT";

export type ModelCategory =
  | "TRANSFORM"
  | "DQ"
  | "STANDARDIZATION"
  | "ENRICHMENT"
  | "LOAD"
  | "OTHER";

export interface SqlAsset {
  asset_id: number;
  asset_code: string;
  domain_code: string;
  version: number;
  asset_type: SqlAssetType;
  model_category: ModelCategory;
  is_active: boolean;
  sql_text: string;
  checksum: string;
  output_table: string | null;
  description: string | null;
  status: AssetStatus;
  created_at: string;
  updated_at: string;
}

export interface SqlAssetIn {
  asset_code: string;
  domain_code: string;
  asset_type?: SqlAssetType;
  model_category?: ModelCategory;
  sql_text: string;
  output_table?: string | null;
  description?: string | null;
  version?: number;
}

export interface SqlAssetUpdate {
  asset_type?: SqlAssetType;
  model_category?: ModelCategory;
  sql_text?: string;
  output_table?: string | null;
  description?: string | null;
}

const BASE = "/v2/sql-assets";

export interface ListSqlAssetsParams {
  domain_code?: string;
  status?: AssetStatus;
  asset_code?: string;
  asset_type?: SqlAssetType;
  model_category?: ModelCategory;
  is_active?: boolean;
}

export function useSqlAssets(params: ListSqlAssetsParams = {}) {
  return useQuery({
    queryKey: ["v2-sql-assets", params],
    queryFn: () => apiRequest<SqlAsset[]>(BASE, { params: { ...params } }),
  });
}

export function useCreateSqlAsset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: SqlAssetIn) =>
      apiRequest<SqlAsset>(BASE, { method: "POST", body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-sql-assets"] }),
  });
}

export function useUpdateSqlAsset(assetId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: SqlAssetUpdate) =>
      apiRequest<SqlAsset>(`${BASE}/${assetId}`, {
        method: "PATCH",
        body: req,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-sql-assets"] }),
  });
}

export function useDeleteSqlAsset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (assetId: number) =>
      apiRequest<void>(`${BASE}/${assetId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-sql-assets"] }),
  });
}

export function useTransitionSqlAsset(assetId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target_status: AssetStatus) =>
      apiRequest<SqlAsset>(`${BASE}/${assetId}/transition`, {
        method: "POST",
        body: { target_status },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-sql-assets"] }),
  });
}

export function useToggleSqlAssetActive(assetId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (is_active: boolean) =>
      apiRequest<SqlAsset>(`${BASE}/${assetId}/active`, {
        method: "POST",
        body: { is_active },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-sql-assets"] }),
  });
}
