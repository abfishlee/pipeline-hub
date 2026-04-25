import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";
import { useAuthStore } from "@/store/auth";

export interface LoginRequest {
  login_id: string;
  password: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface MeResponse {
  user_id: number;
  login_id: string;
  display_name: string;
  email: string | null;
  is_active: boolean;
  roles: string[];
}

export function useLogin() {
  const setTokens = useAuthStore((s) => s.setTokens);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: LoginRequest) =>
      apiRequest<TokenPair>("/v1/auth/login", {
        method: "POST",
        body: req,
        anonymous: true,
      }),
    onSuccess: (tokens) => {
      setTokens(tokens.access_token, tokens.refresh_token);
      void qc.invalidateQueries();
    },
  });
}

export function useMe(enabled = true) {
  const setUser = useAuthStore((s) => s.setUser);
  return useQuery({
    queryKey: ["me"],
    enabled,
    queryFn: async () => {
      const me = await apiRequest<MeResponse>("/v1/auth/me");
      setUser({
        user_id: me.user_id,
        login_id: me.login_id,
        display_name: me.display_name,
        roles: me.roles,
      });
      return me;
    },
  });
}

export function useLogout() {
  const clear = useAuthStore((s) => s.clear);
  const qc = useQueryClient();
  return () => {
    clear();
    qc.clear();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  };
}
