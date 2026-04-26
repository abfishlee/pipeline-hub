import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";

export interface User {
  user_id: number;
  login_id: string;
  display_name: string;
  email: string | null;
  is_active: boolean;
  roles: string[];
  created_at: string;
}

export interface UserCreate {
  login_id: string;
  display_name: string;
  email?: string | null;
  password: string;
  role_codes?: string[];
}

export function useUsers(params: { limit?: number; offset?: number } = {}) {
  return useQuery({
    queryKey: ["users", params],
    queryFn: () => apiRequest<User[]>("/v1/users", { params: { ...params } }),
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: UserCreate) =>
      apiRequest<User>("/v1/users", { method: "POST", body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
}

// Phase 4.0.5 — ctl.role 카탈로그. UsersPage 의 role 드롭다운이 본 endpoint 호출.
export interface Role {
  role_id: number;
  role_code: string;
  role_name: string;
  description: string | null;
}

export function useRoles() {
  return useQuery({
    queryKey: ["users", "roles"],
    queryFn: () => apiRequest<Role[]>("/v1/users/roles"),
    staleTime: 5 * 60 * 1000, // 5분 — role 카탈로그는 거의 안 바뀜.
  });
}
