import { useState } from "react";
import { toast } from "sonner";
import {
  CROWD_REASONS,
  type CrowdReason,
  type CrowdTaskStatus,
  useCrowdTaskDetail,
  useCrowdTasks,
  useUpdateCrowdTaskStatus,
} from "@/api/crowd";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

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

export function CrowdTaskQueue() {
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
