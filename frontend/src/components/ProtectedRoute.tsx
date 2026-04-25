import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "@/store/auth";

interface Props {
  requireRole?: string;
  /** 1개 이상 일치하면 통과 (ADMIN/REVIEWER 같은 다중 허용 시나리오). */
  requireAnyRole?: string[];
}

export function ProtectedRoute({ requireRole, requireAnyRole }: Props) {
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  if (requireRole && (!user || !user.roles.includes(requireRole))) {
    return <Navigate to="/" replace />;
  }

  if (
    requireAnyRole?.length &&
    !(user && requireAnyRole.some((r) => user.roles.includes(r)))
  ) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
