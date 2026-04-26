// Phase 6 Wave 5 — Dry-run Results (workflow-level e2e 결과 트리).
//
// 사용자 시나리오:
//   1. EtlCanvasV2 의 "Dry-run" 버튼 클릭
//   2. /v2/dryrun/workflow/{id} → 박스별 status / row_count / duration
//   3. 본 페이지: 좌측 노드 트리 (success/failed/skipped 뱃지) + 우측 panel
//      - 선택된 노드의 input/output table, row_count, duration_ms
//      - 실패 시 error_message + payload 전체
//   4. 최근 dry-run 이력 (ctl.dry_run_record) 도 함께 표시
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock,
  Play,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import {
  type NodeDryRunResult,
  type WorkflowDryRunResponse,
  useDryRunWorkflow,
  useRecentDryRuns,
} from "@/api/v2/dryrun";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

function nodeStatusVariant(
  s: NodeDryRunResult["status"],
): "success" | "destructive" | "muted" {
  switch (s) {
    case "success":
      return "success";
    case "failed":
      return "destructive";
    case "skipped":
      return "muted";
  }
}

function nodeStatusIcon(s: NodeDryRunResult["status"]) {
  switch (s) {
    case "success":
      return <CheckCircle2 className="h-4 w-4 text-green-600" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-destructive" />;
    case "skipped":
      return <Clock className="h-4 w-4 text-muted-foreground" />;
  }
}

export function DryRunResults() {
  const params = useParams<{ workflowId?: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const wfId = params.workflowId ? Number(params.workflowId) : null;
  const auto = searchParams.get("auto") === "1";

  const dryrun = useDryRunWorkflow();
  const recent = useRecentDryRuns({ kind: "workflow", limit: 10 });

  const [result, setResult] = useState<WorkflowDryRunResponse | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  async function runNow() {
    if (!wfId) {
      toast.error("workflow_id 가 필요합니다.");
      return;
    }
    setResult(null);
    setSelectedKey(null);
    try {
      const res = await dryrun.mutateAsync(wfId);
      setResult(res);
      if (res.nodes.length > 0) setSelectedKey(res.nodes[0].node_key);
      toast.success(
        `dry-run 완료 — 성공 ${res.succeeded} / 실패 ${res.failed} / skip ${res.skipped}`,
      );
      void recent.refetch();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`dry-run 실패: ${msg}`);
    }
  }

  useEffect(() => {
    if (auto && wfId && !result && !dryrun.isPending) {
      void runNow();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, wfId]);

  const selected = useMemo(
    () => result?.nodes.find((n) => n.node_key === selectedKey) ?? null,
    [result, selectedKey],
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            wfId
              ? navigate(`/v2/pipelines/designer/${wfId}`)
              : navigate(-1)
          }
        >
          <ArrowLeft className="h-4 w-4" />
          캔버스로
        </Button>
        <h2 className="text-lg font-semibold">
          Dry-run Results {wfId && <span className="text-muted-foreground">#{wfId}</span>}
        </h2>
        <div className="ml-auto">
          <Button onClick={runNow} disabled={!wfId || dryrun.isPending}>
            <Play className="h-4 w-4" />
            {dryrun.isPending ? "실행 중..." : "Dry-run 실행"}
          </Button>
        </div>
      </div>

      {!result && !dryrun.isPending && (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            "Dry-run 실행" 버튼을 눌러 워크플로의 모든 노드를 위상 정렬 순서로 dry-run
            (rollback). 실 mart 변경 없음.
          </CardContent>
        </Card>
      )}

      {result && (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
              <Badge
                variant={result.status === "success" ? "success" : "destructive"}
              >
                {result.status}
              </Badge>
              <span className="font-semibold">{result.name}</span>
              <span className="text-muted-foreground">
                · 도메인 = {result.domain_code ?? "—"}
              </span>
              <div className="ml-auto flex gap-3 text-xs">
                <span className="text-green-600">
                  성공 {result.succeeded}
                </span>
                <span className="text-destructive">실패 {result.failed}</span>
                <span className="text-muted-foreground">skip {result.skipped}</span>
                <span className="text-muted-foreground">
                  {result.total_duration_ms}ms
                </span>
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-3 gap-4">
            <Card className="col-span-1">
              <CardContent className="space-y-1 p-2">
                <div className="px-2 py-1 text-xs font-semibold uppercase text-muted-foreground">
                  노드 트리 ({result.nodes.length})
                </div>
                {result.nodes.map((n) => (
                  <button
                    key={n.node_key}
                    type="button"
                    onClick={() => setSelectedKey(n.node_key)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md border px-2 py-1 text-left text-xs transition",
                      selectedKey === n.node_key
                        ? "border-primary bg-primary/10"
                        : "border-transparent hover:bg-secondary",
                    )}
                  >
                    {nodeStatusIcon(n.status)}
                    <div className="flex-1 truncate">
                      <div className="font-mono">{n.node_key}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {n.node_type}
                      </div>
                    </div>
                    <Badge variant={nodeStatusVariant(n.status)}>
                      {n.status}
                    </Badge>
                  </button>
                ))}
              </CardContent>
            </Card>

            <Card className="col-span-2">
              <CardContent className="space-y-3 p-4 text-sm">
                {!selected && (
                  <div className="text-xs text-muted-foreground">
                    좌측에서 노드를 선택하세요.
                  </div>
                )}
                {selected && (
                  <>
                    <div className="flex items-center gap-2">
                      <Badge variant={nodeStatusVariant(selected.status)}>
                        {selected.status}
                      </Badge>
                      <code className="text-xs">{selected.node_key}</code>
                      <span className="text-xs text-muted-foreground">
                        ({selected.node_type})
                      </span>
                    </div>
                    <div className="grid grid-cols-3 gap-3 text-xs">
                      <div>
                        <div className="font-semibold uppercase text-muted-foreground">
                          row_count
                        </div>
                        <div className="text-lg">{selected.row_count}</div>
                      </div>
                      <div>
                        <div className="font-semibold uppercase text-muted-foreground">
                          duration
                        </div>
                        <div className="text-lg">
                          {selected.duration_ms}ms
                        </div>
                      </div>
                      <div>
                        <div className="font-semibold uppercase text-muted-foreground">
                          output_table
                        </div>
                        <code className="text-xs">
                          {selected.output_table ?? "—"}
                        </code>
                      </div>
                    </div>

                    {selected.error_message && (
                      <div className="rounded-md border border-destructive bg-destructive/5 p-3">
                        <div className="mb-1 flex items-center gap-1 text-xs font-semibold text-destructive">
                          <AlertTriangle className="h-3 w-3" />
                          오류
                        </div>
                        <pre className="overflow-auto text-xs text-destructive">
                          {selected.error_message}
                        </pre>
                      </div>
                    )}

                    <div>
                      <div className="text-xs font-semibold uppercase text-muted-foreground">
                        payload
                      </div>
                      <pre className="mt-1 max-h-72 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
                        {JSON.stringify(selected.payload, null, 2)}
                      </pre>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      <Card>
        <CardContent className="p-4">
          <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
            최근 workflow dry-run 이력
          </div>
          {recent.isLoading && (
            <div className="text-xs text-muted-foreground">불러오는 중...</div>
          )}
          {recent.data && recent.data.length === 0 && (
            <div className="text-xs text-muted-foreground">
              이력이 없습니다.
            </div>
          )}
          {recent.data && recent.data.length > 0 && (
            <div className="space-y-1 text-xs">
              {recent.data.map((r) => {
                const summary = r.target_summary as {
                  workflow_id?: number;
                  name?: string;
                  succeeded?: number;
                  failed?: number;
                  skipped?: number;
                };
                return (
                  <div
                    key={r.dry_run_id}
                    className="flex items-center gap-2 rounded-md border border-border p-2"
                  >
                    <span className="text-muted-foreground">
                      #{r.dry_run_id}
                    </span>
                    <span className="font-mono">
                      wf={summary.workflow_id} · {summary.name ?? "—"}
                    </span>
                    <span className="text-green-600">
                      성공 {summary.succeeded ?? 0}
                    </span>
                    <span className="text-destructive">
                      실패 {summary.failed ?? 0}
                    </span>
                    <span className="text-muted-foreground">
                      skip {summary.skipped ?? 0}
                    </span>
                    <span className="ml-auto text-muted-foreground">
                      {formatDateTime(r.requested_at)}
                    </span>
                    <span className="text-muted-foreground">
                      {r.duration_ms}ms
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
