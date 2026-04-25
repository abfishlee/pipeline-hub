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
