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
  Globe,
  KeyRound,
  ListChecks,
  LogOut,
  Server,
  Shield,
  ShieldCheck,
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

// 데이터 수집 워크플로 순서로 정렬 (Phase 6 Wave 6 — 메뉴 정리).
// 숨겨진 라우트: /sources (v1 SourcesPage), /pipelines/designer (v1 ETL).
//   기능 중복으로 메뉴에서 제외. 라우트는 backward compat 위해 App.tsx 유지.
const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge },

  // ─── 1. Design — 자산 설계 (개발자 없이) ──────────────────────
  {
    to: "/v2/connectors/public-api",
    label: "Source / API Connector",
    icon: Globe,
    operatorOk: true,
  },
  {
    to: "/v2/inbound-channels/designer",
    label: "Inbound Channel",
    icon: GitBranch,
    operatorOk: true,
  },
  {
    to: "/v2/marts/designer",
    label: "Mart Workbench",
    icon: Database,
    operatorOk: true,
  },
  {
    to: "/v2/mappings/designer",
    label: "Field Mapping Designer",
    icon: Workflow,
    operatorOk: true,
  },
  {
    to: "/v2/transforms/designer",
    label: "Transform Designer",
    icon: Sigma,
    operatorOk: true,
  },
  {
    to: "/v2/quality/designer",
    label: "Quality Workbench",
    icon: ShieldCheck,
    operatorOk: true,
  },

  // ─── 2. Compose & Release — 박스 조립 + 배포 ──────────────────
  {
    to: "/v2/pipelines/designer",
    label: "ETL Canvas",
    icon: Workflow,
    approverOk: true,
  },
  { to: "/pipelines/runs", label: "Pipeline Runs", icon: Workflow },
  { to: "/pipelines/releases", label: "Releases", icon: GitBranch },

  // ─── 3. Operate — 실 운영 (수집/검수/머지) ─────────────────────
  { to: "/raw-objects", label: "Raw Objects", icon: FileBox },
  { to: "/jobs", label: "Collection Jobs", icon: ListChecks },
  { to: "/master-merge", label: "Master Merge", icon: GitMerge, approverOk: true },
  { to: "/sql-studio", label: "SQL Studio", icon: Sigma, operatorOk: true },
  { to: "/crowd-tasks", label: "Review Queue", icon: ClipboardCheck, reviewerOk: true },
  { to: "/runtime", label: "Runtime Monitor", icon: Activity },

  // ─── 4. Admin — 시스템 관리 ────────────────────────────────────
  { to: "/dead-letters", label: "Dead Letters", icon: AlertTriangle, adminOnly: true },
  { to: "/users", label: "Users", icon: Users, adminOnly: true },
  { to: "/api-keys", label: "API Keys", icon: KeyRound, adminOnly: true },
  { to: "/security-events", label: "Security Events", icon: Shield, adminOnly: true },
  { to: "/admin/partitions", label: "Partition Archive", icon: Archive, adminOnly: true },
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
            Logout
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
  if (pathname === "/") return "Dashboard";
  if (pathname.startsWith("/sources")) return "Sources (legacy)";
  if (pathname.startsWith("/v2/connectors/public-api"))
    return "Source / API Connector";
  if (pathname.startsWith("/v2/inbound-channels"))
    return "Inbound Channel Designer";
  if (pathname.startsWith("/v2/mappings/designer"))
    return "Field Mapping Designer";
  if (pathname.startsWith("/v2/transforms/designer"))
    return "Transform Designer";
  if (pathname.startsWith("/v2/quality/designer"))
    return "Quality Workbench";
  if (pathname.startsWith("/v2/marts/designer"))
    return "Mart Workbench";
  if (pathname.startsWith("/v2/dryrun/workflow"))
    return "Dry-run Results";
  if (pathname.startsWith("/v2/publish/"))
    return "Publish Approval";
  if (pathname.startsWith("/jobs")) return "Collection Jobs";
  if (pathname.startsWith("/raw-objects")) return "Raw Objects";
  if (pathname.startsWith("/pipelines/runs/")) return "Pipeline Run Detail";
  if (pathname.startsWith("/pipelines/runs")) return "Pipeline Runs";
  if (pathname.startsWith("/v2/pipelines/designer")) return "ETL Canvas";
  if (pathname.startsWith("/pipelines/designer")) return "Visual ETL Designer (legacy)";
  if (pathname.startsWith("/pipelines/releases")) return "Releases";
  if (pathname.startsWith("/sql-studio")) return "SQL Studio";
  if (pathname.startsWith("/crowd-tasks")) return "Review Queue";
  if (pathname.startsWith("/dead-letters")) return "Dead Letters";
  if (pathname.startsWith("/runtime")) return "Runtime Monitor";
  if (pathname.startsWith("/users")) return "Users";
  if (pathname.startsWith("/api-keys")) return "API Keys";
  if (pathname.startsWith("/security-events")) return "Security Events";
  if (pathname.startsWith("/admin/partitions")) return "Partition Archive";
  if (pathname.startsWith("/master-merge")) return "Master Merge";
  return "";
}
