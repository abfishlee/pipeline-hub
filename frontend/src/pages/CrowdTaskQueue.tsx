import { CheckCircle2, Loader2, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  CROWD_REASONS,
  type CrowdReason,
  type CrowdTaskStatus,
  type ReviewDecision,
  type TaskStatus,
  useCrowdTaskDetail,
  useCrowdTaskDetailV4,
  useCrowdTasks,
  useCrowdTasksV4,
  useResolveConflict,
  useReviewerStats,
  useSubmitReview,
  useUpdateCrowdTaskStatus,
} from "@/api/crowd";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";
import { useAuthStore } from "@/store/auth";

const REASON_LABELS: Record<string, string> = {
  ocr_low_confidence: "OCR 낮음",
  std_low_confidence: "표준화 낮음",
  price_fact_low_confidence: "가격팩트 낮음",
  price_fact_sample_review: "가격팩트 샘플",
};

const STATUS_TABS: CrowdTaskStatus[] = [
  "PENDING",
  "REVIEWING",
  "APPROVED",
  "REJECTED",
];

type ViewMode = "legacy" | "v4";

export function CrowdTaskQueue() {
  const [view, setView] = useState<ViewMode>("v4");
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Button
          variant={view === "v4" ? "default" : "outline"}
          size="sm"
          onClick={() => setView("v4")}
        >
          정식 (Phase 4)
        </Button>
        <Button
          variant={view === "legacy" ? "default" : "outline"}
          size="sm"
          onClick={() => setView("legacy")}
        >
          Legacy (Phase 2.2.10)
        </Button>
      </div>
      {view === "v4" ? <CrowdQueueV4 /> : <CrowdQueueLegacy />}
    </div>
  );
}

function CrowdQueueLegacy() {
  const [status, setStatus] = useState<CrowdTaskStatus>("PENDING");
  const [reason, setReason] = useState<CrowdReason | "">("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const tasks = useCrowdTasks({
    status,
    reason: reason || undefined,
    limit: 50,
  });
  const detail = useCrowdTaskDetail(selectedId);
  const updateStatus = useUpdateCrowdTaskStatus();

  const handleTransition = async (
    target: "REVIEWING" | "APPROVED" | "REJECTED",
  ) => {
    if (selectedId == null) return;
    try {
      await updateStatus.mutateAsync({ crowdTaskId: selectedId, status: target });
      toast.success(`상태 전이: ${target}`, {
        description: "Phase 4 정식 검수 도입 시 placeholder → 실제 검수 흐름으로 교체됩니다.",
      });
    } catch (err) {
      toast.error("전이 실패", { description: String(err) });
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-2 p-4">
          {/* status tabs */}
          <div className="flex gap-1 rounded-md bg-secondary p-1">
            {STATUS_TABS.map((s) => (
              <button
                key={s}
                onClick={() => {
                  setStatus(s);
                  setSelectedId(null);
                }}
                className={cn(
                  "rounded-sm px-3 py-1 text-xs font-medium transition",
                  status === s
                    ? "bg-background shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {s}
              </button>
            ))}
          </div>
          <span className="mx-2 text-xs text-muted-foreground">|</span>
          {/* reason filter */}
          <button
            onClick={() => setReason("")}
            className={cn(
              "rounded-md border px-2 py-1 text-xs",
              reason === "" ? "border-primary bg-primary/10" : "border-border",
            )}
          >
            (전체)
          </button>
          {CROWD_REASONS.map((r) => (
            <button
              key={r}
              onClick={() => setReason(r)}
              className={cn(
                "rounded-md border px-2 py-1 text-xs",
                reason === r ? "border-primary bg-primary/10" : "border-border",
              )}
            >
              {REASON_LABELS[r] ?? r}
            </button>
          ))}
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
        <Card>
          <CardContent className="p-0">
            <Table>
              <Thead>
                <Tr>
                  <Th>ID</Th>
                  <Th>raw_object</Th>
                  <Th>reason</Th>
                  <Th>status</Th>
                  <Th>생성</Th>
                </Tr>
              </Thead>
              <Tbody>
                {tasks.isLoading && (
                  <Tr>
                    <Td colSpan={5} className="text-center text-muted-foreground">
                      로딩 중…
                    </Td>
                  </Tr>
                )}
                {!tasks.isLoading && (tasks.data?.length ?? 0) === 0 && (
                  <Tr>
                    <Td colSpan={5} className="text-center text-muted-foreground">
                      해당 조건에 작업이 없습니다.
                    </Td>
                  </Tr>
                )}
                {tasks.data?.map((row) => (
                  <Tr
                    key={row.crowd_task_id}
                    onClick={() => setSelectedId(row.crowd_task_id)}
                    className={cn(
                      "cursor-pointer",
                      selectedId === row.crowd_task_id && "bg-secondary/40",
                    )}
                  >
                    <Td className="font-mono">#{row.crowd_task_id}</Td>
                    <Td className="font-mono text-xs">
                      {row.raw_object_id} / {row.partition_date}
                    </Td>
                    <Td>
                      <Badge variant="muted">{REASON_LABELS[row.reason] ?? row.reason}</Badge>
                    </Td>
                    <Td>{row.status}</Td>
                    <Td>{formatDateTime(row.created_at)}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            {selectedId == null && (
              <p className="text-sm text-muted-foreground">
                좌측 표에서 항목을 선택하면 상세가 표시됩니다.
              </p>
            )}
            {selectedId != null && detail.isLoading && (
              <p className="text-sm text-muted-foreground">상세 로딩 중…</p>
            )}
            {detail.data && (
              <div className="space-y-3 text-sm">
                <div>
                  <span className="text-xs text-muted-foreground">ID</span>
                  <div className="font-mono">#{detail.data.crowd_task_id}</div>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">사유</span>
                  <div>{REASON_LABELS[detail.data.reason] ?? detail.data.reason}</div>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">payload</span>
                  <pre className="max-h-32 overflow-auto rounded-md bg-secondary p-2 text-xs">
                    {JSON.stringify(detail.data.payload_json, null, 2)}
                  </pre>
                </div>
                {detail.data.raw_object_payload && (
                  <div>
                    <span className="text-xs text-muted-foreground">
                      raw_object payload
                    </span>
                    <pre className="max-h-40 overflow-auto rounded-md bg-secondary p-2 text-xs">
                      {JSON.stringify(detail.data.raw_object_payload, null, 2)}
                    </pre>
                  </div>
                )}
                {detail.data.raw_object_uri && (
                  <div className="break-all text-xs">
                    <span className="text-muted-foreground">object_uri</span>
                    <div className="font-mono">{detail.data.raw_object_uri}</div>
                  </div>
                )}
                {detail.data.ocr_results.length > 0 && (
                  <div>
                    <span className="text-xs text-muted-foreground">
                      OCR 결과 ({detail.data.ocr_results.length} 페이지)
                    </span>
                    <ul className="mt-1 space-y-2">
                      {detail.data.ocr_results.map((o) => (
                        <li
                          key={o.ocr_result_id}
                          className="rounded-md border border-border bg-secondary/30 p-2"
                        >
                          <div className="text-xs text-muted-foreground">
                            page {o.page_no ?? "-"} · {o.engine_name} · conf{" "}
                            {o.confidence_score ?? "-"}
                          </div>
                          <div className="mt-1 line-clamp-3 text-xs">
                            {o.text_content ?? "(빈 텍스트)"}
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="flex flex-wrap gap-2 border-t border-border pt-3">
                  {detail.data.status === "PENDING" && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleTransition("REVIEWING")}
                      disabled={updateStatus.isPending}
                    >
                      검수 시작
                    </Button>
                  )}
                  {(detail.data.status === "PENDING" ||
                    detail.data.status === "REVIEWING") && (
                    <>
                      <Button
                        size="sm"
                        onClick={() => handleTransition("APPROVED")}
                        disabled={updateStatus.isPending}
                      >
                        승인 (placeholder)
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleTransition("REJECTED")}
                        disabled={updateStatus.isPending}
                      >
                        반려 (placeholder)
                      </Button>
                    </>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  ※ 승인/반려는 Phase 4 정식 Crowd 검수 UI 도입 시 실제 비즈니스
                  로직(상품 매핑 확정, 가격팩트 재반영 등)에 연결됩니다. 현재는
                  상태 전이 마킹만.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ===========================================================================
// Phase 4.2.1 — 정식 검수 화면 (이중 검수, 합의, CONFLICT 해결)
// ===========================================================================
const TASK_STATUS_TABS: TaskStatus[] = [
  "PENDING",
  "REVIEWING",
  "CONFLICT",
  "APPROVED",
  "REJECTED",
];

const STATUS_BADGE_V4: Record<
  TaskStatus,
  "default" | "muted" | "success" | "warning" | "destructive"
> = {
  PENDING: "muted",
  REVIEWING: "warning",
  CONFLICT: "destructive",
  APPROVED: "success",
  REJECTED: "destructive",
  CANCELLED: "muted",
};

function CrowdQueueV4() {
  const [status, setStatus] = useState<TaskStatus>("PENDING");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const tasks = useCrowdTasksV4({ status, limit: 100 });
  const stats = useReviewerStats();

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_420px]">
      <div className="space-y-3">
        <Card>
          <CardContent className="flex flex-wrap items-center gap-2 p-3 text-sm">
            {TASK_STATUS_TABS.map((s) => (
              <Button
                key={s}
                size="sm"
                variant={status === s ? "default" : "outline"}
                onClick={() => {
                  setStatus(s);
                  setSelectedId(null);
                }}
              >
                {s}
                {tasks.data && status === s ? ` (${tasks.data.length})` : ""}
              </Button>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <Table>
              <Thead>
                <Tr>
                  <Th>id</Th>
                  <Th>kind</Th>
                  <Th>priority</Th>
                  <Th>status</Th>
                  <Th>created</Th>
                  <Th></Th>
                </Tr>
              </Thead>
              <Tbody>
                {tasks.isLoading && (
                  <Tr>
                    <Td colSpan={6} className="text-center text-muted-foreground">
                      로딩 중…
                    </Td>
                  </Tr>
                )}
                {!tasks.isLoading && (tasks.data?.length ?? 0) === 0 && (
                  <Tr>
                    <Td colSpan={6} className="text-center text-muted-foreground">
                      해당 status 의 task 없음
                    </Td>
                  </Tr>
                )}
                {tasks.data?.map((t) => (
                  <Tr
                    key={t.crowd_task_id}
                    className={cn(
                      "cursor-pointer hover:bg-secondary",
                      selectedId === t.crowd_task_id && "bg-primary/10",
                    )}
                    onClick={() => setSelectedId(t.crowd_task_id)}
                  >
                    <Td className="font-mono text-xs">#{t.crowd_task_id}</Td>
                    <Td className="font-mono text-xs">{t.task_kind}</Td>
                    <Td className="text-xs">
                      <Badge variant={t.priority >= 8 ? "warning" : "muted"}>
                        P{t.priority}
                      </Badge>
                    </Td>
                    <Td>
                      <Badge variant={STATUS_BADGE_V4[t.status]}>{t.status}</Badge>
                    </Td>
                    <Td className="text-xs">{formatDateTime(t.created_at)}</Td>
                    <Td className="text-xs text-muted-foreground">
                      {t.requires_double_review ? "이중" : ""}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </CardContent>
        </Card>

        {stats.data && stats.data.length > 0 && (
          <Card>
            <CardContent className="p-3 text-xs">
              <h4 className="mb-2 text-sm font-semibold">검수자 30일 통계</h4>
              <Table>
                <Thead>
                  <Tr>
                    <Th>검수자</Th>
                    <Th>건수</Th>
                    <Th>평균</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {stats.data.map((s) => (
                    <Tr key={s.reviewer_id}>
                      <Td className="font-mono">{s.display_name}</Td>
                      <Td>{s.count_30d}</Td>
                      <Td>
                        {s.avg_decision_ms
                          ? `${(s.avg_decision_ms / 1000).toFixed(1)}s`
                          : "-"}
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </CardContent>
          </Card>
        )}
      </div>

      <V4DetailPanel taskId={selectedId} onClose={() => setSelectedId(null)} />
    </div>
  );
}

function V4DetailPanel({
  taskId,
  onClose,
}: {
  taskId: number | null;
  onClose: () => void;
}) {
  const detail = useCrowdTaskDetailV4(taskId);
  const submit = useSubmitReview();
  const resolve = useResolveConflict();
  const user = useAuthStore((s) => s.user);
  const [comment, setComment] = useState("");
  const isResolver = !!user?.roles.some(
    (r) => r === "ADMIN" || r === "APPROVER",
  );

  if (taskId == null) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          좌측에서 task 를 선택하세요.
        </CardContent>
      </Card>
    );
  }

  if (detail.isLoading || !detail.data) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          로딩 중…
        </CardContent>
      </Card>
    );
  }

  const t = detail.data;
  const myReview = t.reviews.find((r) => r.reviewer_id === user?.user_id);
  const canReview =
    !myReview &&
    (t.status === "PENDING" || t.status === "REVIEWING") &&
    !!user?.roles.some(
      (r) => r === "REVIEWER" || r === "APPROVER" || r === "ADMIN",
    );

  const handleReview = async (decision: ReviewDecision) => {
    if (!taskId) return;
    try {
      await submit.mutateAsync({ taskId, decision, comment: comment || null });
      toast.success(`${decision} 제출됨`);
      setComment("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "제출 실패");
    }
  };

  const handleResolve = async (final_decision: "APPROVE" | "REJECT") => {
    if (!taskId) return;
    try {
      await resolve.mutateAsync({
        taskId,
        final_decision,
        note: comment || null,
      });
      toast.success(`CONFLICT 해결 — ${final_decision}`);
      setComment("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "해결 실패");
    }
  };

  return (
    <Card className="sticky top-4">
      <CardContent className="space-y-3 p-4 text-sm">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold">Task #{t.crowd_task_id}</h3>
          <Badge variant={STATUS_BADGE_V4[t.status]}>{t.status}</Badge>
          <Badge variant={t.priority >= 8 ? "warning" : "muted"}>
            P{t.priority}
          </Badge>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto text-xs text-muted-foreground underline"
          >
            닫기
          </button>
        </div>

        <div>
          <h4 className="text-xs font-semibold text-muted-foreground">
            task_kind
          </h4>
          <code className="text-xs">{t.task_kind}</code>
        </div>

        {Object.keys(t.payload).length > 0 && (
          <details>
            <summary className="cursor-pointer text-xs font-semibold text-muted-foreground">
              payload ({Object.keys(t.payload).length} keys)
            </summary>
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-muted/40 p-2 font-mono text-[10px]">
              {JSON.stringify(t.payload, null, 2)}
            </pre>
          </details>
        )}

        {t.assignments.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-muted-foreground">
              배정된 검수자 ({t.assignments.length})
            </h4>
            <ul className="text-xs">
              {t.assignments.map((a) => (
                <li key={a.assignment_id}>
                  reviewer={a.reviewer_id} ·{" "}
                  {a.released_at ? "released" : "active"}
                </li>
              ))}
            </ul>
          </div>
        )}

        {t.reviews.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-muted-foreground">
              리뷰 ({t.reviews.length})
            </h4>
            <ul className="space-y-1 text-xs">
              {t.reviews.map((r) => (
                <li
                  key={r.review_id}
                  className="rounded border border-border bg-background p-2"
                >
                  <span className="font-mono">reviewer={r.reviewer_id}</span>
                  <span className="ml-2 font-semibold">
                    {r.decision === "APPROVE"
                      ? "✓ APPROVE"
                      : r.decision === "REJECT"
                        ? "✗ REJECT"
                        : "↷ SKIP"}
                  </span>
                  {r.comment && (
                    <span className="ml-2 text-muted-foreground">
                      "{r.comment}"
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {t.decision && (
          <div className="rounded border border-emerald-300 bg-emerald-50 p-2 text-xs">
            <h4 className="font-semibold text-emerald-700">최종 합의</h4>
            <div>
              {t.decision.final_decision} · {t.decision.consensus_kind}
            </div>
            {Object.keys(t.decision.effect_payload).length > 0 && (
              <pre className="mt-1 font-mono text-[10px]">
                {JSON.stringify(t.decision.effect_payload, null, 2)}
              </pre>
            )}
          </div>
        )}

        {t.status === "CONFLICT" && isResolver && (
          <div className="space-y-2 rounded border border-rose-300 bg-rose-50 p-2 text-xs">
            <div className="flex items-center gap-1 font-semibold text-rose-700">
              <ShieldAlert className="h-3 w-3" />
              충돌 — 관리자 해결 필요
            </div>
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="해결 코멘트 (선택)"
              className="h-8 text-xs"
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => handleResolve("APPROVE")}
                disabled={resolve.isPending}
              >
                <CheckCircle2 className="h-3 w-3" /> APPROVE 로 해결
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => handleResolve("REJECT")}
                disabled={resolve.isPending}
              >
                <X className="h-3 w-3" /> REJECT 로 해결
              </Button>
            </div>
          </div>
        )}

        {canReview && (
          <div className="space-y-2 rounded border border-primary/30 bg-primary/5 p-2 text-xs">
            <h4 className="font-semibold">내 결정</h4>
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="코멘트 (선택)"
              className="h-8 text-xs"
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => handleReview("APPROVE")}
                disabled={submit.isPending}
              >
                {submit.isPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-3 w-3" />
                )}
                APPROVE
              </Button>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => handleReview("REJECT")}
                disabled={submit.isPending}
              >
                <X className="h-3 w-3" /> REJECT
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleReview("SKIP")}
                disabled={submit.isPending}
              >
                SKIP
              </Button>
            </div>
          </div>
        )}

        {myReview && (
          <div className="rounded border border-border bg-muted/40 p-2 text-xs">
            내 결정 이미 제출됨 — <strong>{myReview.decision}</strong>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
