import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "@/store/auth";

interface Props {
  requireRole?: string;
}

export function ProtectedRoute({ requireRole }: Props) {
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);

  if (!accessToken) {
    return <Navigate to="/login" replace />;
  }

  if (requireRole && (!user || !user.roles.includes(requireRole))) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
