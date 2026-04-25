import { useAuthStore } from "@/store/auth";

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id?: string | null;
    details?: Record<string, unknown>;
  };
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly code: string;
  public readonly details?: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  /** auth 헤더 미부착 (login 등). */
  anonymous?: boolean;
  /** multipart 요청 시 body 를 FormData 로 직접 전달. */
  formData?: FormData;
  /** query string params. */
  params?: Record<string, string | number | boolean | undefined | null>;
}

const BASE_URL = "";

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  let url = `${BASE_URL}${path}`;
  if (params) {
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v == null) continue;
      usp.append(k, String(v));
    }
    const qs = usp.toString();
    if (qs) url += (url.includes("?") ? "&" : "?") + qs;
  }
  return url;
}

export async function apiRequest<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers ?? {}) };

  if (!options.anonymous) {
    const token = useAuthStore.getState().accessToken;
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = headers["Content-Type"] ?? "application/json";
    body = JSON.stringify(options.body);
  }

  const url = buildUrl(path, options.params);
  const res = await fetch(url, {
    method: options.method ?? "GET",
    headers,
    body,
  });

  // 401 → 자동 logout + /login 이동.
  if (res.status === 401 && !options.anonymous) {
    useAuthStore.getState().clear();
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const contentType = res.headers.get("content-type") ?? "";

  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = res.statusText || "request failed";
    let details: Record<string, unknown> | undefined;
    if (contentType.includes("application/json")) {
      try {
        const data = (await res.json()) as Partial<ApiErrorBody>;
        if (data.error) {
          code = data.error.code;
          message = data.error.message;
          details = data.error.details;
        }
      } catch {
        /* ignore parse */
      }
    }
    throw new ApiError(res.status, code, message, details);
  }

  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}
