import {
  Activity,
  ClipboardList,
  Database,
  Gauge,
  GitBranch,
  Globe,
  Inbox,
  ListChecks,
  LogOut,
  PanelTop,
  Server,
  ShieldCheck,
  Sigma,
  Sparkles,
  Users,
  Workflow,
} from "lucide-react";
import type React from "react";
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
  approverOk?: boolean;
  operatorOk?: boolean;
}

interface NavSection {
  kind: "section";
  label: string;
  adminOnly?: boolean;
}

type NavEntry = NavItem | NavSection;

function section(label: string, options: Pick<NavSection, "adminOnly"> = {}): NavSection {
  return { kind: "section", label, ...options };
}

function isSection(item: NavEntry): item is NavSection {
  return "kind" in item && item.kind === "section";
}

const NAV_ITEMS: NavEntry[] = [
  { to: "/", label: "Dashboard", icon: Gauge },

  section("1. 자산 설계"),
  { to: "/v2/sources", label: "Sources", icon: PanelTop, operatorOk: true },
  { to: "/v2/connectors/public-api", label: "API Pull", icon: Globe, operatorOk: true },
  {
    to: "/v2/inbound-channels/designer",
    label: "Inbound Push",
    icon: GitBranch,
    operatorOk: true,
  },
  {
    to: "/v2/mappings/designer",
    label: "Field Mapping",
    icon: Workflow,
    operatorOk: true,
  },
  {
    to: "/v2/standardization",
    label: "Standardization",
    icon: Sparkles,
    operatorOk: true,
  },
  {
    to: "/v2/quality/designer",
    label: "DQ / Quality",
    icon: ShieldCheck,
    operatorOk: true,
  },
  {
    to: "/v2/transforms/designer",
    label: "Transform",
    icon: Sigma,
    operatorOk: true,
  },
  {
    to: "/v2/marts/designer",
    label: "Mart Designer",
    icon: Database,
    operatorOk: true,
  },

  section("2. 수집 / 실행"),
  {
    to: "/v2/pipelines/designer",
    label: "ETL Canvas",
    icon: Workflow,
    approverOk: true,
  },
  { to: "/pipelines/runs", label: "Jobs & Runs", icon: ListChecks },
  {
    to: "/v2/inbound-events",
    label: "Inbound Inbox",
    icon: Inbox,
    operatorOk: true,
  },
  {
    to: "/v2/review-queue",
    label: "Review Queue",
    icon: ClipboardList,
    operatorOk: true,
  },

  section("3. 운영 모니터링"),
  { to: "/v2/operations/dashboard", label: "Monitoring", icon: Activity },
  {
    to: "/v2/mart-freshness",
    label: "Mart Freshness",
    icon: Database,
    operatorOk: true,
  },

  section("4. 시스템 관리", { adminOnly: true }),
  { to: "/users", label: "Users", icon: Users, adminOnly: true },
];

export function Layout(_: PropsWithChildren) {
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.roles.includes("ADMIN");
  const isApprover = isAdmin || !!user?.roles.includes("APPROVER");
  const isOperator = isApprover || !!user?.roles.includes("OPERATOR");
  const isReviewer =
    isAdmin || !!user?.roles.some((r) => r === "REVIEWER" || r === "APPROVER");
  const logout = useLogout();
  const location = useLocation();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-secondary/30">
      <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-background">
        <div className="flex h-14 items-center gap-2 border-b border-border px-4">
          <Server className="h-5 w-5 text-primary" />
          <Link to="/" className="text-base font-semibold">
            Pipeline Hub
          </Link>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto p-2">
          {NAV_ITEMS.filter((it) => {
            if (isSection(it)) return it.adminOnly ? isAdmin : true;
            if (it.adminOnly) return isAdmin;
            if (it.approverOk) return isApprover;
            if (it.operatorOk) return isOperator;
            if (it.reviewerOk) return isReviewer;
            return true;
          }).map((item, index) => {
            if (isSection(item)) {
              return (
                <div
                  key={`${item.label}-${index}`}
                  className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                >
                  {item.label}
                </div>
              );
            }
            return (
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
            );
          })}
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
          <Button variant="outline" size="sm" className="w-full" onClick={logout}>
            <LogOut className="h-4 w-4" />
            Logout
          </Button>
        </div>
      </aside>

      <main className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 items-center justify-between border-b border-border bg-background px-6">
          <h1 className="text-lg font-semibold">
            {currentTitle(location.pathname)}
          </h1>
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
  if (pathname.startsWith("/v2/sources")) return "Sources";
  if (pathname.startsWith("/v2/connectors/public-api")) return "API Pull Source";
  if (pathname.startsWith("/v2/inbound-channels")) return "Inbound Push Channel";
  if (pathname.startsWith("/v2/inbound-events")) return "Inbound Inbox";
  if (pathname.startsWith("/v2/mappings/designer")) return "Field Mapping";
  if (pathname.startsWith("/v2/standardization")) return "Standardization";
  if (pathname.startsWith("/v2/review-queue")) return "Review Queue";
  if (pathname.startsWith("/v2/transforms/designer")) return "Transform";
  if (pathname.startsWith("/v2/quality/designer")) return "DQ / Quality";
  if (pathname.startsWith("/v2/marts/designer")) return "Mart Designer";
  if (pathname.startsWith("/v2/operations/dashboard")) return "Monitoring";
  if (pathname.startsWith("/v2/mart-freshness")) return "Mart Freshness";
  if (pathname.startsWith("/v2/service-mart")) return "Service Mart Viewer";
  if (pathname.startsWith("/v2/dryrun/workflow")) return "Dry-run Results";
  if (pathname.startsWith("/v2/publish/")) return "Publish Approval";
  if (pathname.startsWith("/jobs")) return "Collection Jobs";
  if (pathname.startsWith("/raw-objects")) return "Raw Objects";
  if (pathname.startsWith("/pipelines/runs/")) return "Pipeline Run Detail";
  if (pathname.startsWith("/pipelines/runs")) return "Jobs & Runs";
  if (pathname.startsWith("/v2/pipelines/designer")) return "ETL Canvas";
  if (pathname.startsWith("/pipelines/designer")) return "Visual ETL Designer";
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
  if (pathname.startsWith("/sources")) return "Sources (legacy)";
  return "";
}
