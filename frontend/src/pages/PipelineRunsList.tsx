import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  type OnHoldRunOut,
  type PipelineRunStatus,
  type QualityResultOut,
  type WorkflowStatus,
  useApproveHold,
  useOnHoldRuns,
  useRejectHold,
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
  ON_HOLD: "text-orange-600",
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
  "ON_HOLD",
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
  const onHoldRuns = useOnHoldRuns({ limit: 50 });
  const [holdModal, setHoldModal] = useState<OnHoldRunOut | null>(null);
  const user = useAuthStore((s) => s.user);
  const canDesign =
    !!user?.roles.some((r) => r === "ADMIN" || r === "APPROVER");
  const canApprove =
    !!user?.roles.some((r) => r === "ADMIN" || r === "APPROVER");

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="text-sm font-semibold">워크플로 목록</h3>
            {canDesign && (
              <Link
                to="/v2/pipelines/designer"
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
                        to={`/v2/pipelines/designer/${w.workflow_id}`}
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

      {(onHoldRuns.data?.length ?? 0) > 0 && (
        <Card>
          <CardContent className="space-y-2 p-4">
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-orange-700">
                ON_HOLD ({onHoldRuns.data?.length ?? 0})
              </h3>
              <span className="text-xs text-muted-foreground">
                DQ 게이트에 걸린 실행 — APPROVER 승인 또는 반려가 필요합니다.
              </span>
            </div>
            <Table>
              <Thead>
                <Tr>
                  <Th>run_id</Th>
                  <Th>workflow_id</Th>
                  <Th>run_date</Th>
                  <Th>failed_node</Th>
                  <Th>fail_count</Th>
                  <Th></Th>
                </Tr>
              </Thead>
              <Tbody>
                {onHoldRuns.data?.map((r) => (
                  <Tr key={r.pipeline_run_id}>
                    <Td className="font-mono">#{r.pipeline_run_id}</Td>
                    <Td className="font-mono">{r.workflow_id}</Td>
                    <Td>{r.run_date}</Td>
                    <Td className="font-mono text-xs">
                      {r.failed_node_keys.join(", ") || "-"}
                    </Td>
                    <Td className="text-rose-600">
                      {r.quality_results.length}
                    </Td>
                    <Td>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setHoldModal(r)}
                      >
                        검토
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </CardContent>
        </Card>
      )}

      {holdModal && (
        <HoldDecisionModal
          run={holdModal}
          canApprove={canApprove}
          onClose={() => setHoldModal(null)}
        />
      )}

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

// ---------------------------------------------------------------------------
// HoldDecisionModal — DQ 게이트 승인/반려 (Phase 4.2.2)
// ---------------------------------------------------------------------------
function HoldDecisionModal({
  run,
  canApprove,
  onClose,
}: {
  run: OnHoldRunOut;
  canApprove: boolean;
  onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const approve = useApproveHold();
  const reject = useRejectHold();
  const inFlight = approve.isPending || reject.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-3xl overflow-auto rounded-lg bg-background p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            DQ 게이트 — run #{run.pipeline_run_id}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
          >
            ×
          </button>
        </div>

        <div className="mb-3 text-xs text-muted-foreground">
          workflow {run.workflow_id} · {run.run_date} · failed nodes:{" "}
          <span className="font-mono">{run.failed_node_keys.join(", ") || "-"}</span>
        </div>

        <div className="mb-4 space-y-3">
          {run.quality_results.length === 0 && (
            <p className="text-sm text-muted-foreground">
              실패한 DQ 결과가 없습니다 (이미 처리되었을 수 있음).
            </p>
          )}
          {run.quality_results.map((qr) => (
            <FailedRuleCard key={qr.quality_result_id} qr={qr} />
          ))}
        </div>

        <div className="mb-3">
          <label
            htmlFor="hold-reason"
            className="mb-1 block text-xs font-medium text-muted-foreground"
          >
            사유 (선택)
          </label>
          <textarea
            id="hold-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="검토 결과 요약 또는 반려 사유"
            className="w-full rounded-md border border-input bg-background p-2 text-sm"
          />
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={inFlight}>
            닫기
          </Button>
          {canApprove ? (
            <>
              <Button
                variant="destructive"
                onClick={() =>
                  reject.mutate(
                    { runId: run.pipeline_run_id, reason: reason || null },
                    { onSuccess: onClose },
                  )
                }
                disabled={inFlight}
              >
                {reject.isPending ? "반려 중…" : "반려 (CANCEL + rollback)"}
              </Button>
              <Button
                onClick={() =>
                  approve.mutate(
                    { runId: run.pipeline_run_id, reason: reason || null },
                    { onSuccess: onClose },
                  )
                }
                disabled={inFlight}
              >
                {approve.isPending ? "승인 중…" : "승인 (재개)"}
              </Button>
            </>
          ) : (
            <span className="text-xs text-muted-foreground">
              승인/반려는 ADMIN/APPROVER 권한이 필요합니다.
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function FailedRuleCard({ qr }: { qr: QualityResultOut }) {
  return (
    <div className="rounded-md border border-rose-200 bg-rose-50/40 p-3 text-xs">
      <div className="mb-1 flex items-center gap-2">
        <Badge variant="destructive">{qr.severity}</Badge>
        <span className="font-mono">{qr.check_kind}</span>
        <span className="text-muted-foreground">on {qr.target_table}</span>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap text-[11px] text-foreground/80">
        {JSON.stringify(qr.details_json, null, 2)}
      </pre>
      {qr.sample_json.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-muted-foreground">
            failed sample rows ({qr.sample_json.length})
          </summary>
          <pre className="overflow-x-auto whitespace-pre-wrap text-[11px]">
            {JSON.stringify(qr.sample_json, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
