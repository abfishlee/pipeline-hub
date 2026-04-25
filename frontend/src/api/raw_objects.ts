import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./client";

export type ObjectType =
  | "JSON"
  | "XML"
  | "CSV"
  | "HTML"
  | "PDF"
  | "IMAGE"
  | "DB_ROW"
  | "RECEIPT_IMAGE";

export type RawStatus = "RECEIVED" | "PROCESSED" | "FAILED" | "DISCARDED";

export interface RawObjectSummary {
  raw_object_id: number;
  source_id: number;
  job_id: number | null;
  object_type: ObjectType;
  status: RawStatus;
  received_at: string;
  partition_date: string;
  has_inline_payload: boolean;
  object_uri_present: boolean;
}

export interface RawObjectDetail {
  raw_object_id: number;
  source_id: number;
  job_id: number | null;
  object_type: ObjectType;
  status: RawStatus;
  content_hash: string;
  idempotency_key: string | null;
  received_at: string;
  partition_date: string;
  payload_json: Record<string, unknown> | null;
  object_uri: string | null;
  download_url: string | null;
}

export interface ListRawObjectsParams {
  source_id?: number;
  status?: RawStatus;
  object_type?: ObjectType;
  from?: string;
  to?: string;
  limit?: number;
  offset?: number;
}

export function useRawObjects(params: ListRawObjectsParams = {}) {
  return useQuery({
    queryKey: ["raw-objects", params],
    queryFn: () =>
      apiRequest<RawObjectSummary[]>("/v1/raw-objects", { params: { ...params } }),
  });
}

export function useRawObjectDetail(
  rawObjectId: number | null,
  partitionDate?: string,
) {
  return useQuery({
    queryKey: ["raw-objects", rawObjectId, partitionDate],
    enabled: rawObjectId != null,
    queryFn: () =>
      apiRequest<RawObjectDetail>(`/v1/raw-objects/${rawObjectId}`, {
        params: partitionDate ? { partition_date: partitionDate } : undefined,
      }),
  });
}
