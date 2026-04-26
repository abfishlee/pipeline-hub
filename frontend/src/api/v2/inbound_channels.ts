// Phase 7 Wave 1A — Inbound channel client (외부 push 채널 등록).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export type ChannelStatus = "DRAFT" | "REVIEW" | "APPROVED" | "PUBLISHED";
export type ChannelKind =
  | "WEBHOOK"
  | "FILE_UPLOAD"
  | "OCR_RESULT"
  | "CRAWLER_RESULT";
export type AuthMethod = "hmac_sha256" | "api_key" | "mtls";

export interface InboundChannel {
  channel_id: number;
  channel_code: string;
  domain_code: string;
  name: string;
  description: string | null;
  channel_kind: ChannelKind;
  secret_ref: string;
  auth_method: AuthMethod;
  expected_content_type: string | null;
  max_payload_bytes: number;
  rate_limit_per_min: number;
  replay_window_sec: number;
  workflow_id: number | null;
  status: ChannelStatus;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface InboundChannelIn {
  channel_code: string;
  domain_code: string;
  name: string;
  description?: string | null;
  channel_kind: ChannelKind;
  secret_ref: string;
  auth_method?: AuthMethod;
  expected_content_type?: string | null;
  max_payload_bytes?: number;
  rate_limit_per_min?: number;
  replay_window_sec?: number;
  workflow_id?: number | null;
}

export interface InboundChannelUpdate {
  name?: string;
  description?: string | null;
  secret_ref?: string;
  expected_content_type?: string | null;
  max_payload_bytes?: number;
  rate_limit_per_min?: number;
  replay_window_sec?: number;
  workflow_id?: number | null;
  is_active?: boolean;
}

const BASE = "/v2/inbound-channels";

export interface ListInboundChannelsParams {
  domain_code?: string;
  channel_kind?: ChannelKind;
  status?: ChannelStatus;
}

export function useInboundChannels(params: ListInboundChannelsParams = {}) {
  return useQuery({
    queryKey: ["v2-inbound-channels", params],
    queryFn: () =>
      apiRequest<InboundChannel[]>(BASE, { params: { ...params } }),
  });
}

export function useCreateInboundChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: InboundChannelIn) =>
      apiRequest<InboundChannel>(BASE, { method: "POST", body: req }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["v2-inbound-channels"] }),
  });
}

export function useUpdateInboundChannel(channelId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: InboundChannelUpdate) =>
      apiRequest<InboundChannel>(`${BASE}/${channelId}`, {
        method: "PATCH",
        body: req,
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["v2-inbound-channels"] }),
  });
}

export function useDeleteInboundChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (channelId: number) =>
      apiRequest<void>(`${BASE}/${channelId}`, { method: "DELETE" }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["v2-inbound-channels"] }),
  });
}

export function useTransitionInboundChannel(channelId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target_status: ChannelStatus) =>
      apiRequest<InboundChannel>(`${BASE}/${channelId}/transition`, {
        method: "POST",
        body: { target_status },
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["v2-inbound-channels"] }),
  });
}
