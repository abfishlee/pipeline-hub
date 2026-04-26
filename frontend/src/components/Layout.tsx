import {
  Activity,
  AlertTriangle,
  ClipboardCheck,
  Database,
  FileBox,
  Gauge,
  GitBranch,
  Archive,
  GitMerge,
  KeyRound,
  ListChecks,
  LogOut,
  Server,
  Shield,
  Sigma,
  Users,
  Workflow,
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
  reviewerOk?: boolean;
  /** ADMIN 또는 APPROVER 만 노출 (Visual ETL Designer 전용). */
  approverOk?: boolean;
  /** ADMIN/APPROVER/OPERATOR 만 노출 (SQL Studio). */
  operatorOk?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "대시보드", icon: Gauge },
  { to: "/sources", label: "데이터 소스", icon: Database },
  { to: "/jobs", label: "수집 작업", icon: ListChecks },
  { to: "/raw-objects", label: "원천 데이터", icon: FileBox },
  { to: "/pipelines/runs", label: "파이프라인 실행", icon: Workflow },
  {
    to: "/pipelines/designer",
    label: "Visual ETL Designer",
    icon: Workflow,
    approverOk: true,
  },
  { to: "/pipelines/releases", label: "배포 이력", icon: GitBranch },
  { to: "/master-merge", label: "제품 머지", icon: GitMerge, approverOk: true },
  { to: "/sql-studio", label: "SQL Studio", icon: Sigma, operatorOk: true },
  { to: "/crowd-tasks", label: "검수 큐", icon: ClipboardCheck, reviewerOk: true },
  { to: "/dead-letters", label: "Dead Letter", icon: AlertTriangle, adminOnly: true },
  { to: "/runtime", label: "Runtime 모니터", icon: Activity },
  { to: "/users", label: "사용자 관리", icon: Users, adminOnly: true },
  { to: "/api-keys", label: "API Keys", icon: KeyRound, adminOnly: true },
  { to: "/security-events", label: "보안 이벤트", icon: Shield, adminOnly: true },
  { to: "/admin/partitions", label: "파티션 아카이브", icon: Archive, adminOnly: true },
];

export function Layout(_: PropsWithChildren) {
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.roles.includes("ADMIN");
  const isApprover = isAdmin || !!user?.roles.includes("APPROVER");
  const isOperator =
    isApprover || !!user?.roles.includes("OPERATOR");
  const isReviewer =
    isAdmin ||
    !!user?.roles.some((r) => r === "REVIEWER" || r === "APPROVER");
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
          {NAV_ITEMS.filter((it) => {
            if (it.adminOnly) return isAdmin;
            if (it.approverOk) return isApprover;
            if (it.operatorOk) return isOperator;
            if (it.reviewerOk) return isReviewer;
            return true;
          }).map((item) => (
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
  if (pathname.startsWith("/pipelines/runs/")) return "파이프라인 실행 상세";
  if (pathname.startsWith("/pipelines/runs")) return "파이프라인 실행 이력";
  if (pathname.startsWith("/pipelines/designer")) return "Visual ETL Designer";
  if (pathname.startsWith("/pipelines/releases")) return "배포 이력";
  if (pathname.startsWith("/sql-studio")) return "SQL Studio";
  if (pathname.startsWith("/crowd-tasks")) return "검수 큐";
  if (pathname.startsWith("/dead-letters")) return "Dead Letter";
  if (pathname.startsWith("/runtime")) return "Runtime 모니터";
  if (pathname.startsWith("/users")) return "사용자 관리";
  if (pathname.startsWith("/api-keys")) return "API Keys";
  if (pathname.startsWith("/security-events")) return "보안 이벤트";
  if (pathname.startsWith("/admin/partitions")) return "파티션 아카이브";
  if (pathname.startsWith("/master-merge")) return "제품 머지";
  return "";
}
