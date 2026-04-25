import {
  Database,
  FileBox,
  Gauge,
  ListChecks,
  LogOut,
  Server,
  Users,
} from "lucide-react";
import { type PropsWithChildren } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useLogout } from "@/api/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/store/auth";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  adminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "대시보드", icon: Gauge },
  { to: "/sources", label: "데이터 소스", icon: Database },
  { to: "/jobs", label: "수집 작업", icon: ListChecks },
  { to: "/raw-objects", label: "원천 데이터", icon: FileBox },
  { to: "/users", label: "사용자 관리", icon: Users, adminOnly: true },
];

export function Layout(_: PropsWithChildren) {
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.roles.includes("ADMIN");
  const logout = useLogout();
  const location = useLocation();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-secondary/30">
      {/* Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-background">
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <Server className="h-5 w-5 text-primary" />
          <Link to="/" className="text-base font-semibold">
            Pipeline Hub
          </Link>
        </div>
        <nav className="flex-1 space-y-1 p-2">
          {NAV_ITEMS.filter((it) => !it.adminOnly || isAdmin).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition",
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-foreground/80 hover:bg-secondary",
                )
              }
            >
              <item.icon className="h-4 w-4" />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-border p-3 text-xs text-muted-foreground">
          <div className="mb-1 truncate font-medium text-foreground">
            {user?.display_name ?? "-"}
          </div>
          <div className="mb-2 truncate">{user?.login_id}</div>
          <div className="mb-3 flex flex-wrap gap-1">
            {user?.roles.map((r) => (
              <Badge key={r} variant="muted">
                {r}
              </Badge>
            ))}
          </div>
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={logout}
          >
            <LogOut className="h-4 w-4" />
            로그아웃
          </Button>
        </div>
      </aside>

      {/* Content */}
      <main className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 items-center justify-between border-b border-border bg-background px-6">
          <h1 className="text-lg font-semibold">{currentTitle(location.pathname)}</h1>
        </header>
        <div className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function currentTitle(pathname: string): string {
  if (pathname === "/") return "대시보드";
  if (pathname.startsWith("/sources")) return "데이터 소스";
  if (pathname.startsWith("/jobs")) return "수집 작업";
  if (pathname.startsWith("/raw-objects")) return "원천 데이터";
  if (pathname.startsWith("/users")) return "사용자 관리";
  return "";
}
