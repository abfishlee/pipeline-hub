import { ApiError } from "@/api/client";

export function apiErrorMessage(error: unknown, fallback = "요청 처리 중 오류가 발생했습니다.") {
  if (error instanceof ApiError) {
    const prefix = error.status >= 500 ? "서버 오류" : "요청 오류";
    return `${prefix}: ${error.message}`;
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
