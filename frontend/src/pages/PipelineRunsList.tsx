import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  type PipelineRunStatus,
  type WorkflowStatus,
  useSearchRuns,
  useWorkflows,
} from "@/api/pipelines";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { useAuthStore } from "@/store/auth";

const STATUS_COLORS: Record<PipelineRunStatus, string> = {
  PENDING: "text-muted-foreground",
  RUNNING: "text-amber-600",
  SUCCESS: "text-emerald-600",
  FAILED: "text-rose-600",
  CANCELLED: "text-muted-foreground",
};

const WORKFLOW_BADGE: Record<WorkflowStatus, "default" | "muted" | "destructive"> = {
  DRAFT: "muted",
  PUBLISHED: "default",
  ARCHIVED: "destructive",
};

const STATUS_OPTIONS: PipelineRunStatus[] = [
  "PENDING",
  "RUNNING",
  "SUCCESS",
  "FAILED",
  "CANCELLED",
];

export function PipelineRunsList() {
  const workflows = useWorkflows({ limit: 100 });
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<PipelineRunStatus | "">("");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const runs = useSearchRuns({
    workflow_id: selectedWorkflowId,
    status: statusFilter || null,
    from: fromDate || null,
    to: toDate || null,
    limit: 200,
  });
  const user = useAuthStore((s) => s.user);
  const canDesign =
    !!user?.roles.some((r) => r === "ADMIN" || r === "APPROVER");

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-sm font-semibold">워크플로 목록</h3>
            {canDesign && (
              <Link
                to="/pipelines/designer"
                className="ml-auto inline-flex h-8 items-center gap-2 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-3 w-3" />
                신규 디자이너
              </Link>
            )}
          </div>
          <Table>
            <Thead>
              <Tr>
                <Th>workflow_id</Th>
                <Th>name</Th>
                <Th>version</Th>
                <Th>status</Th>
                <Th>updated</Th>
                <Th></Th>
              </Tr>
            </Thead>
            <Tbody>
              {workflows.isLoading && (
                <Tr>
                  <Td colSpan={6} className="text-center text-muted-foreground">
                    로딩 중…
                  </Td>
                </Tr>
              )}
              {!workflows.isLoading && (workflows.data?.length ?? 0) === 0 && (
                <Tr>
                  <Td colSpan={6} className="text-center text-muted-foreground">
                    워크플로가 없습니다.
                    {canDesign && " 우측 상단 '신규 디자이너' 로 만들어 보세요."}
                  </Td>
                </Tr>
              )}
              {workflows.data?.map((w) => (
                <Tr key={w.workflow_id}>
                  <Td className="font-mono">#{w.workflow_id}</Td>
                  <Td>{w.name}</Td>
                  <Td className="font-mono">v{w.version}</Td>
                  <Td>
                    <Badge variant={WORKFLOW_BADGE[w.status]}>{w.status}</Badge>
                  </Td>
                  <Td>{formatDateTime(w.updated_at)}</Td>
                  <Td className="space-x-2 whitespace-nowrap">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setSelectedWorkflowId(w.workflow_id)}
                    >
                      이력
                    </Button>
                    {canDesign && (
                      <Link
                        to={`/pipelines/designer/${w.workflow_id}`}
                        className="inline-flex h-8 items-center gap-2 rounded-md px-3 text-sm font-medium text-foreground/80 hover:bg-accent hover:text-accent-foreground"
                      >
                        <Pencil className="h-3 w-3" />
                        {w.status === "DRAFT" ? "편집" : "보기"}
                      </Link>
                    )}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
          <span className="text-muted-foreground">workflow:</span>
          <select
            value={selectedWorkflowId ?? ""}
            onChange={(e) =>
              setSelectedWorkflowId(e.target.value ? Number(e.target.value) : null)
            }
            className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">(전체)</option>
            {workflows.data?.map((w) => (
              <option key={w.workflow_id} value={w.workflow_id}>
                {w.name} v{w.version} [{w.status}]
              </option>
            ))}
          </select>
          <span className="text-muted-foreground">status:</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as PipelineRunStatus | "")}
            className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">(전체)</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <span className="text-muted-foreground">기간:</span>
          <input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-2 text-xs"
          />
          <span>→</span>
          <input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-2 text-xs"
          />
          {(selectedWorkflowId || statusFilter || fromDate || toDate) && (
            <button
              type="button"
              className="text-xs text-muted-foreground underline"
              onClick={() => {
                setSelectedWorkflowId(null);
                setStatusFilter("");
                setFromDate("");
                setToDate("");
              }}
            >
              필터 초기화
            </button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <Thead>
              <Tr>
                <Th>run_id</Th>
                <Th>workflow_id</Th>
                <Th>run_date</Th>
                <Th>status</Th>
                <Th>started</Th>
                <Th>finished</Th>
                <Th></Th>
              </Tr>
            </Thead>
            <Tbody>
              {runs.isLoading && (
                <Tr>
                  <Td colSpan={7} className="text-center text-muted-foreground">
                    로딩 중…
                  </Td>
                </Tr>
              )}
              {!runs.isLoading && (runs.data?.length ?? 0) === 0 && (
                <Tr>
                  <Td colSpan={7} className="text-center text-muted-foreground">
                    실행 이력이 없습니다. POST /v1/pipelines/{"{id}"}/runs 로 트리거해 주세요.
                  </Td>
                </Tr>
              )}
              {runs.data?.map((r) => (
                <Tr key={r.pipeline_run_id}>
                  <Td className="font-mono">#{r.pipeline_run_id}</Td>
                  <Td className="font-mono">{r.workflow_id}</Td>
                  <Td>{r.run_date}</Td>
                  <Td className={cn("font-medium", STATUS_COLORS[r.status])}>
                    {r.status}
                  </Td>
                  <Td>{r.started_at ? formatDateTime(r.started_at) : "-"}</Td>
                  <Td>{r.finished_at ? formatDateTime(r.finished_at) : "-"}</Td>
                  <Td>
                    <Link
                      to={`/pipelines/runs/${r.pipeline_run_id}`}
                      className="text-primary underline"
                    >
                      상세
                    </Link>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
