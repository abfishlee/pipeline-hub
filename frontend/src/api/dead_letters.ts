import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

export interface DeadLetter {
  dl_id: number;
  origin: string;
  payload_json: Record<string, unknown>;
  error_message: string | null;
  stack_trace: string | null;
  failed_at: string;
  replayed_at: string | null;
  replayed_by: number | null;
}

export interface DeadLetterReplayResult {
  dl_id: number;
  origin: string;
  enqueued_message_id: string | null;
  replayed_at: string;
  replayed_by: number;
}

export interface ListDeadLettersParams {
  replayed?: boolean;
  origin?: string;
  limit?: number;
  offset?: number;
}

export function useDeadLetters(params: ListDeadLettersParams = {}) {
  return useQuery({
    queryKey: ["dead-letters", params],
    queryFn: () =>
      apiRequest<DeadLetter[]>("/v1/dead-letters", {
        params: { ...params, replayed: params.replayed ?? false },
      }),
  });
}

export function useReplayDeadLetter() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (dlId: number) =>
      apiRequest<DeadLetterReplayResult>(`/v1/dead-letters/${dlId}/replay`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dead-letters"] });
    },
  });
}
