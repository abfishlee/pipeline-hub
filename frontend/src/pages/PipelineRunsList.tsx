import { useQuery } from "@tanstack/react-query";
import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "@/api/client";
import {
  type PipelineRunOut,
  type PipelineRunStatus,
  type WorkflowStatus,
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

function useRecentRuns(workflowId: number | null) {
  return useQuery({
    queryKey: ["pipelines", "recent-runs", workflowId],
    queryFn: () =>
      apiRequest<PipelineRunOut[]>(`/v1/pipelines/runs`, {
        // 백엔드에 list 엔드포인트가 아직 없는 경우, 단일 GET 으로 fallback.
        // Phase 3.2.3 한정 — 단일 조회만 노출. 후속 sub-phase 에서 list API 추가.
      }).catch(() => [] as PipelineRunOut[]),
    enabled: workflowId == null, // 단일 workflow detail 진입 시는 비활성.
  });
}

export function PipelineRunsList() {
  const workflows = useWorkflows({ limit: 100 });
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(null);
  const runs = useRecentRuns(selectedWorkflowId);
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
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <span className="text-sm text-muted-foreground">실행 이력 필터:</span>
          <select
            value={selectedWorkflowId ?? ""}
            onChange={(e) =>
              setSelectedWorkflowId(e.target.value ? Number(e.target.value) : null)
            }
            className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">(전체)</option>
            {workflows.data?.map((w) => (
              <option key={w.workflow_id} value={w.workflow_id}>
                {w.name} v{w.version} [{w.status}]
              </option>
            ))}
          </select>
          <p className="basis-full text-xs text-muted-foreground">
            ※ Phase 3.2.3 한정 — runs 목록 API 는 후속 sub-phase 에서 정식 도입. 현재는
            workflow 상세에서 진입한 단일 run 만 실시간 갱신.
          </p>
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
