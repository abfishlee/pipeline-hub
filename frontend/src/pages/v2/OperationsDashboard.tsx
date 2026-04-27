// Phase 7 Wave 5/6 — Operations Dashboard.
//
// 시나리오 8 (15~20 채널 동시 운영) 의 핵심 화면.
// - 좌: 채널 (workflow) 목록 + 24h 성공률 + 마지막 run 상태
// - 우: 선택된 채널의 노드별 heatmap (success/failed/skipped count)
// - 상단: 전체 summary (workflow / runs / success rate / rows / pending replay)
// - inbound dispatch (Wave 6) — pending envelope 일괄 처리 버튼
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  PlayCircle,
  RefreshCw,
  XCircle,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import {
  useDispatchPending,
  useFailureSummary,
  useHourlyTrend,
  useOperationsChannels,
  useOperationsSummary,
  useTriggerRerun,
  useWorkflowHeatmap,
} from "@/api/v2/operations";
import { HourlyTrendChart } from "@/components/dashboard/HourlyTrendChart";
import {
  DispatcherHealthCard,
  ProviderCostCard,
  SlaLagCard,
  StaleChannelsPanel,
} from "@/components/dashboard/RealOperationCards";
import { RecentFailuresPanel } from "@/components/dashboard/RecentFailuresPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

function statusVariant(
  s: string | null,
): "default" | "secondary" | "success" | "warning" | "muted" | "destructive" {
  switch (s) {
    case "SUCCESS":
      return "success";
    case "FAILED":
      return "destructive";
    case "RUNNING":
    case "PENDING":
      return "warning";
    case "ON_HOLD":
      return "warning";
    case "CANCELLED":
      return "muted";
    case "SKIPPED":
      return "muted";
    default:
      return "muted";
  }
}

export function OperationsDashboard() {
  const summary = useOperationsSummary();
  const channels = useOperationsChannels(100);
  const failures = useFailureSummary();
  const hourlyTrend = useHourlyTrend();
  const dispatch = useDispatchPending();
  const rerun = useTriggerRerun();
  const [selectedWfId, setSelectedWfId] = useState<number | null>(null);
  const heatmap = useWorkflowHeatmap(selectedWfId);

  const selectedChannel = useMemo(
    () => channels.data?.find((c) => c.workflow_id === selectedWfId) ?? null,
    [channels.data, selectedWfId],
  );

  async function handleDispatch() {
    try {
      const res = await dispatch.mutateAsync(50);
      toast.success(
        `dispatch 완료 — pending ${res.pending_before}→${res.pending_after}, ` +
          `dispatched=${res.dispatched}, manual=${res.manual}, failed=${res.failed}`,
      );
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`dispatch 실패: ${msg}`);
    }
  }

  async function handleRerun(workflowId: number, name: string) {
    if (!confirm(`${name} 워크플로를 재실행할까요?`)) return;
    try {
      const res = await rerun.mutateAsync(workflowId);
      toast.success(
        `재실행 트리거됨 (run_id=${res.pipeline_run_id}, status=${res.status})`,
      );
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`재실행 실패: ${msg}`);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Operations Dashboard</h2>
          <p className="text-sm text-muted-foreground">
            모든 채널 (workflow) 의 24h 운영 현황. 30초 polling. Phase 7 Wave 5.
          </p>
        </div>
        <Button onClick={handleDispatch} disabled={dispatch.isPending}>
          <Zap className="h-4 w-4" />
          Dispatch Pending Inbound
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <SummaryCard
          icon={<Activity className="h-4 w-4 text-primary" />}
          label="Workflows (PUBLISHED)"
          value={summary.data?.workflow_count ?? "—"}
        />
        <SummaryCard
          icon={<PlayCircle className="h-4 w-4 text-blue-500" />}
          label="Runs (24h)"
          value={summary.data?.runs_24h ?? "—"}
          sub={
            summary.data
              ? `${summary.data.success_24h} success / ${summary.data.failed_24h} failed`
              : undefined
          }
        />
        <SummaryCard
          icon={
            (summary.data?.success_rate_pct ?? 100) >= 95 ? (
              <CheckCircle2 className="h-4 w-4 text-green-600" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-amber-600" />
            )
          }
          label="Success Rate (24h)"
          value={
            summary.data
              ? `${summary.data.success_rate_pct.toFixed(1)}%`
              : "—"
          }
          sub={
            summary.data
              ? `rows ${summary.data.rows_ingested_24h.toLocaleString()}`
              : undefined
          }
        />
        <SummaryCard
          icon={
            (summary.data?.pending_replay ?? 0) > 0 ? (
              <AlertTriangle className="h-4 w-4 text-destructive" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-green-600" />
            )
          }
          label="Pending Replay"
          value={summary.data?.pending_replay ?? 0}
          sub={
            (summary.data?.provider_failures_24h ?? 0) > 0
              ? `provider err ${summary.data?.provider_failures_24h}`
              : undefined
          }
        />
      </div>

      {/* Phase 8.5 — Real Operation 카드 3종 (SLA / Dispatcher / Provider 비용) */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <SlaLagCard />
        <DispatcherHealthCard />
        <div className="md:col-span-1" />
      </div>

      {/* Phase 8.5 — 채널 데이터 신선도 + Provider 비용 */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <StaleChannelsPanel />
        <ProviderCostCard />
      </div>

      {/* Hourly Trend Chart — Phase 8.2 */}
      <HourlyTrendChart data={hourlyTrend.data} />

      {/* Recent Failures (Phase 8.4) — 운영자 즉시 대응 */}
      <RecentFailuresPanel />

      {/* Failure Categories — Phase 8.1 */}
      {failures.data && failures.data.length > 0 && (
        <Card>
          <CardContent className="space-y-2 p-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase text-muted-foreground">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
              실패 원인 분류 (24h)
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
              {failures.data.map((f) => (
                <div
                  key={f.category}
                  className="rounded-md border border-rose-200 bg-rose-50 p-2 text-xs"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="font-semibold text-rose-700">
                      {f.category}
                    </span>
                    <span className="ml-auto text-base font-semibold text-rose-700">
                      {f.failed_count}
                    </span>
                  </div>
                  {f.sample_workflow_name && (
                    <div className="mt-0.5 text-[10px] text-rose-700/80">
                      {f.sample_workflow_name}
                    </div>
                  )}
                  {f.sample_error && (
                    <div className="mt-1 line-clamp-2 text-[10px] text-rose-700/80">
                      {f.sample_error}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Channels + heatmap */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="col-span-1">
          <CardContent className="space-y-1 p-2">
            <div className="px-2 py-1 text-xs font-semibold uppercase text-muted-foreground">
              Channels ({channels.data?.length ?? 0})
            </div>
            {channels.isLoading && (
              <div className="px-2 py-1 text-xs text-muted-foreground">
                불러오는 중...
              </div>
            )}
            {channels.data && channels.data.length === 0 && (
              <div className="px-2 py-1 text-xs text-muted-foreground">
                workflow 가 없습니다.
              </div>
            )}
            {channels.data?.map((c) => (
              <button
                key={c.workflow_id}
                type="button"
                onClick={() => setSelectedWfId(c.workflow_id)}
                className={cn(
                  "flex w-full items-start gap-2 rounded-md border px-2 py-2 text-left text-xs transition",
                  selectedWfId === c.workflow_id
                    ? "border-primary bg-primary/10"
                    : "border-transparent hover:bg-secondary",
                )}
              >
                <div className="flex-1 truncate">
                  <div className="flex items-center gap-1">
                    <span className="font-mono">{c.workflow_name}</span>
                    {c.status === "PUBLISHED" ? (
                      <Badge variant="success">{c.status}</Badge>
                    ) : (
                      <Badge variant="muted">{c.status}</Badge>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
                    {c.last_run_at ? (
                      <>
                        <Clock className="h-2.5 w-2.5" />
                        {formatDateTime(c.last_run_at)}
                        {c.last_run_status && (
                          <Badge variant={statusVariant(c.last_run_status)}>
                            {c.last_run_status}
                          </Badge>
                        )}
                      </>
                    ) : (
                      <span>no run yet</span>
                    )}
                  </div>
                  <div className="mt-0.5 flex gap-2 text-[10px]">
                    <span className="text-green-600">
                      ✓ {c.success_24h}
                    </span>
                    <span className="text-destructive">✗ {c.failed_24h}</span>
                    <span className="text-muted-foreground">
                      / {c.runs_24h} (24h)
                    </span>
                    <span className="ml-auto text-muted-foreground">
                      {c.success_rate_pct.toFixed(0)}%
                    </span>
                  </div>
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        <Card className="col-span-2">
          <CardContent className="space-y-3 p-4">
            {!selectedChannel && (
              <div className="text-xs text-muted-foreground">
                좌측에서 채널을 선택하면 노드별 heatmap (7일) 이 표시됩니다.
              </div>
            )}
            {selectedChannel && (
              <>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold">
                      {selectedChannel.workflow_name}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      workflow #{selectedChannel.workflow_id} ·{" "}
                      {selectedChannel.schedule_cron ?? "no cron"}{" "}
                      {selectedChannel.schedule_enabled ? "(enabled)" : ""}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        handleRerun(
                          selectedChannel.workflow_id,
                          selectedChannel.workflow_name,
                        )
                      }
                      disabled={
                        rerun.isPending ||
                        selectedChannel.status !== "PUBLISHED"
                      }
                      className="rounded-md bg-primary px-2 py-1 text-[11px] font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                      title={
                        selectedChannel.status === "PUBLISHED"
                          ? "이 워크플로 즉시 재실행"
                          : "PUBLISHED 워크플로만 재실행 가능"
                      }
                    >
                      <PlayCircle className="mr-0.5 inline h-3 w-3" />
                      재실행
                    </button>
                    <Link
                      to={`/v2/pipelines/designer/${selectedChannel.workflow_id}`}
                      className="text-xs text-primary hover:underline"
                    >
                      캔버스로 ↗
                    </Link>
                    <Link
                      to={`/v2/dryrun/workflow/${selectedChannel.workflow_id}?auto=1`}
                      className="text-xs text-primary hover:underline"
                    >
                      Dry-run ↗
                    </Link>
                  </div>
                </div>

                <div>
                  <div className="text-xs font-semibold uppercase text-muted-foreground">
                    Node Heatmap (7d)
                  </div>
                  {heatmap.isLoading && (
                    <div className="text-xs text-muted-foreground">
                      불러오는 중...
                    </div>
                  )}
                  {heatmap.data && heatmap.data.length === 0 && (
                    <div className="text-xs text-muted-foreground">
                      아직 실행 이력이 없습니다.
                    </div>
                  )}
                  {heatmap.data && heatmap.data.length > 0 && (
                    <div className="space-y-1">
                      {heatmap.data.map((cell) => {
                        const total =
                          cell.success_count +
                          cell.failed_count +
                          cell.skipped_count;
                        const successPct =
                          total > 0 ? (cell.success_count / total) * 100 : 0;
                        return (
                          <div
                            key={cell.node_key}
                            className="flex items-center gap-2 rounded-md border border-border p-2 text-xs"
                          >
                            <div className="w-24 truncate">
                              <code>{cell.node_key}</code>
                            </div>
                            <div className="w-32 text-[10px] text-muted-foreground">
                              {cell.node_type}
                            </div>
                            <div className="flex-1">
                              <div className="h-2 overflow-hidden rounded bg-muted">
                                <div className="flex h-full">
                                  <div
                                    className="bg-green-500"
                                    style={{
                                      width: `${
                                        total > 0
                                          ? (cell.success_count / total) * 100
                                          : 0
                                      }%`,
                                    }}
                                    title={`success ${cell.success_count}`}
                                  />
                                  <div
                                    className="bg-destructive"
                                    style={{
                                      width: `${
                                        total > 0
                                          ? (cell.failed_count / total) * 100
                                          : 0
                                      }%`,
                                    }}
                                    title={`failed ${cell.failed_count}`}
                                  />
                                  <div
                                    className="bg-muted-foreground/40"
                                    style={{
                                      width: `${
                                        total > 0
                                          ? (cell.skipped_count / total) * 100
                                          : 0
                                      }%`,
                                    }}
                                    title={`skipped ${cell.skipped_count}`}
                                  />
                                </div>
                              </div>
                            </div>
                            <div className="flex w-32 gap-1 text-[10px]">
                              <span className="text-green-600">
                                ✓ {cell.success_count}
                              </span>
                              {cell.failed_count > 0 && (
                                <span className="text-destructive">
                                  <XCircle className="inline h-2.5 w-2.5" />
                                  {cell.failed_count}
                                </span>
                              )}
                              {cell.skipped_count > 0 && (
                                <span className="text-muted-foreground">
                                  ⊘ {cell.skipped_count}
                                </span>
                              )}
                            </div>
                            <div className="w-12 text-right text-[10px] text-muted-foreground">
                              {successPct.toFixed(0)}%
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <p className="text-[11px] text-muted-foreground">
        ※ 30초 polling — 실시간 SSE 는 run detail 페이지 (
        <code>/pipelines/runs/{"{run_id}"}</code>) 에서.{" "}
        <RefreshCw className="inline h-3 w-3" /> Dispatch 버튼은 외부 push
        envelope (RECEIVED) 을 workflow trigger 로 일괄 변환.
      </p>
    </div>
  );
}

interface SummaryCardProps {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  sub?: string;
}

function SummaryCard({ icon, label, value, sub }: SummaryCardProps) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {icon}
          {label}
        </div>
        <div className="mt-1 text-2xl font-semibold">{value}</div>
        {sub && (
          <div className="mt-0.5 text-[10px] text-muted-foreground">{sub}</div>
        )}
      </CardContent>
    </Card>
  );
}
