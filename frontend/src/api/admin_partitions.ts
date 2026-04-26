import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type PartitionArchiveStatus =
  | "PENDING"
  | "COPYING"
  | "COPIED"
  | "DETACHED"
  | "DROPPED"
  | "RESTORED"
  | "FAILED";

export interface PartitionArchiveOut {
  archive_id: number;
  schema_name: string;
  table_name: string;
  partition_name: string;
  row_count: number | null;
  byte_size: number | null;
  checksum: string | null;
  object_uri: string | null;
  status: PartitionArchiveStatus;
  archived_at: string | null;
  restored_at: string | null;
  restored_to: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ArchiveActionResponse {
  archive_id: number;
  status: string;
  detail: string;
  object_uri: string | null;
  row_count: number | null;
}

export function useArchives(params: {
  status?: PartitionArchiveStatus | null;
  limit?: number;
} = {}) {
  return useQuery({
    queryKey: ["admin-partitions", params],
    queryFn: () =>
      apiRequest<PartitionArchiveOut[]>("/v1/admin/partitions", {
        params: {
          status: params.status ?? undefined,
          limit: params.limit ?? 100,
        },
      }),
    refetchInterval: 30_000,
  });
}

export function useRunArchive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (archiveId: number) =>
      apiRequest<ArchiveActionResponse>(
        `/v1/admin/partitions/${archiveId}/run`,
        { method: "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-partitions"] }),
  });
}

export function useRestoreArchive() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      archiveId,
      target_table,
    }: {
      archiveId: number;
      target_table?: string | null;
    }) =>
      apiRequest<ArchiveActionResponse>(
        `/v1/admin/partitions/${archiveId}/restore`,
        { method: "POST", body: { target_table: target_table ?? null } },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-partitions"] }),
  });
}
