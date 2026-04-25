import {
  Background,
  Controls,
  type Edge,
  MiniMap,
  type Node,
  ReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { useParams } from "react-router-dom";
import {
  type NodeRunStatus,
  usePipelineRun,
  useWorkflowDetail,
} from "@/api/pipelines";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { usePipelineRunSSE } from "@/hooks/usePipelineRunSSE";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

const STATUS_STYLE: Record<NodeRunStatus, { bg: string; border: string; text: string }> = {
  PENDING: {
    bg: "bg-secondary",
    border: "border-border",
    text: "text-muted-foreground",
  },
  READY: {
    bg: "bg-blue-50",
    border: "border-blue-400",
    text: "text-blue-700",
  },
  RUNNING: {
    bg: "bg-amber-50",
    border: "border-amber-500",
    text: "text-amber-700",
  },
  SUCCESS: {
    bg: "bg-emerald-50",
    border: "border-emerald-500",
    text: "text-emerald-700",
  },
  FAILED: {
    bg: "bg-rose-50",
    border: "border-rose-500",
    text: "text-rose-700",
  },
  SKIPPED: {
    bg: "bg-zinc-100",
    border: "border-zinc-400",
    text: "text-zinc-500",
  },
  CANCELLED: {
    bg: "bg-zinc-100",
    border: "border-zinc-400",
    text: "text-zinc-500",
  },
};

export function PipelineRunDetail() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId ? Number(params.runId) : null;
  const run = usePipelineRun(runId);
  const workflow = useWorkflowDetail(run.data?.workflow_id ?? null);
  const sse = usePipelineRunSSE(runId);

  // node_definition_id → 최신 node_run status 매핑
  const nodeStatusByDef = useMemo(() => {
    const m: Record<number, NodeRunStatus> = {};
    for (const nr of run.data?.node_runs ?? []) {
      m[nr.node_definition_id] = nr.status;
    }
    return m;
  }, [run.data?.node_runs]);

  const flowNodes: Node[] = useMemo(() => {
    if (!workflow.data) return [];
    return workflow.data.nodes.map((n) => {
      const status = (nodeStatusByDef[n.node_id] ?? "PENDING") as NodeRunStatus;
      const style = STATUS_STYLE[status] ?? STATUS_STYLE.PENDING;
      return {
        id: String(n.node_id),
        position: { x: n.position_x, y: n.position_y },
        data: {
          label: (
            <div
              className={cn(
                "rounded-md border-2 px-3 py-2 text-xs",
                style.bg,
                style.border,
                style.text,
              )}
            >
              <div className="font-mono font-semibold">{n.node_key}</div>
              <div className="text-[10px] opacity-70">{n.node_type}</div>
              <div className="mt-1 text-[10px]">{status}</div>
            </div>
          ),
        },
        style: { width: 180, padding: 0, border: "none", background: "transparent" },
      };
    });
  }, [workflow.data, nodeStatusByDef]);

  const flowEdges: Edge[] = useMemo(() => {
    if (!workflow.data) return [];
    return workflow.data.edges.map((e) => ({
      id: String(e.edge_id),
      source: String(e.from_node_id),
      target: String(e.to_node_id),
      animated: false,
    }));
  }, [workflow.data]);

  if (runId == null) {
    return <div className="text-sm text-muted-foreground">잘못된 run_id 입니다.</div>;
  }

  return (
    <div className="flex h-full flex-col gap-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
          <span className="font-mono">#{runId}</span>
          {run.data && (
            <>
              <Badge variant={run.data.status === "FAILED" ? "destructive" : "muted"}>
                {run.data.status}
              </Badge>
              <span className="text-xs text-muted-foreground">
                workflow_id={run.data.workflow_id} · run_date={run.data.run_date}
              </span>
              <span className="text-xs text-muted-foreground">
                started {run.data.started_at ? formatDateTime(run.data.started_at) : "-"} ·
                finished {run.data.finished_at ? formatDateTime(run.data.finished_at) : "-"}
              </span>
              <span
                className={cn(
                  "ml-auto text-xs",
                  sse.connected ? "text-emerald-600" : "text-muted-foreground",
                )}
              >
                ● {sse.connected ? "SSE 실시간" : "SSE 미연결"}
                {sse.errorCount > 0 && ` (오류 ${sse.errorCount})`}
              </span>
            </>
          )}
        </CardContent>
      </Card>

      <Card className="flex-1">
        <CardContent className="h-full p-0">
          <div className="h-[480px] w-full">
            <ReactFlow
              nodes={flowNodes}
              edges={flowEdges}
              fitView
              proOptions={{ hideAttribution: true }}
              defaultEdgeOptions={{ type: "smoothstep" }}
            >
              <Background gap={16} />
              <Controls />
              <MiniMap pannable zoomable />
            </ReactFlow>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <h3 className="mb-2 text-sm font-semibold">노드 실행 이력</h3>
          <div className="space-y-1 text-xs">
            {run.data?.node_runs.map((nr) => {
              const s = STATUS_STYLE[nr.status] ?? STATUS_STYLE.PENDING;
              return (
                <div
                  key={nr.node_run_id}
                  className={cn(
                    "rounded-md border px-3 py-2",
                    s.bg,
                    s.border,
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-semibold">{nr.node_key}</span>
                    <span className="text-muted-foreground">{nr.node_type}</span>
                    <span className={cn("ml-auto font-medium", s.text)}>{nr.status}</span>
                  </div>
                  {nr.error_message && (
                    <div className="mt-1 text-rose-700">{nr.error_message}</div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
