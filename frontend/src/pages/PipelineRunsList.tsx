import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { apiRequest } from "@/api/client";
import {
  type PipelineRunOut,
  type PipelineRunStatus,
  useWorkflows,
} from "@/api/pipelines";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

const STATUS_COLORS: Record<PipelineRunStatus, string> = {
  PENDING: "text-muted-foreground",
  RUNNING: "text-amber-600",
  SUCCESS: "text-emerald-600",
  FAILED: "text-rose-600",
  CANCELLED: "text-muted-foreground",
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

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <span className="text-sm text-muted-foreground">Workflow:</span>
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
