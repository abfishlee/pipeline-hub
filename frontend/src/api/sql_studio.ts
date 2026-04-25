import { useMutation } from "@tanstack/react-query";
import { apiRequest } from "./client";

export interface SqlValidateResponse {
  valid: boolean;
  error: string | null;
  referenced_tables: string[];
}

export function useValidateSql() {
  return useMutation({
    mutationFn: (sql: string) =>
      apiRequest<SqlValidateResponse>("/v1/sql-studio/validate", {
        method: "POST",
        body: { sql },
      }),
  });
}
