import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type SourceType =
  | "API"
  | "OCR"
  | "DB"
  | "CRAWLER"
  | "CROWD"
  | "RECEIPT"
  | "APP";

export interface DataSource {
  source_id: number;
  source_code: string;
  source_name: string;
  source_type: SourceType;
  retailer_id: number | null;
  owner_team: string | null;
  is_active: boolean;
  config_json: Record<string, unknown>;
  schedule_cron: string | null;
  created_at: string;
  updated_at: string;
}

export interface DataSourceCreate {
  source_code: string;
  source_name: string;
  source_type: SourceType;
  retailer_id?: number | null;
  owner_team?: string | null;
  is_active?: boolean;
  config_json?: Record<string, unknown>;
  schedule_cron?: string | null;
}

export type DataSourceUpdate = Partial<Omit<DataSourceCreate, "source_code">>;

export interface ListSourcesParams {
  limit?: number;
  offset?: number;
  source_type?: SourceType;
  is_active?: boolean;
}

export function useSources(params: ListSourcesParams = {}) {
  return useQuery({
    queryKey: ["sources", params],
    queryFn: () =>
      apiRequest<DataSource[]>("/v1/sources", {
        params: { ...params },
      }),
  });
}

export function useSource(sourceId: number | null) {
  return useQuery({
    queryKey: ["sources", sourceId],
    enabled: sourceId != null,
    queryFn: () => apiRequest<DataSource>(`/v1/sources/${sourceId}`),
  });
}

export function useCreateSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: DataSourceCreate) =>
      apiRequest<DataSource>("/v1/sources", { method: "POST", body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useUpdateSource(sourceId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: DataSourceUpdate) =>
      apiRequest<DataSource>(`/v1/sources/${sourceId}`, {
        method: "PATCH",
        body: patch,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceId: number) =>
      apiRequest<void>(`/v1/sources/${sourceId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
}
