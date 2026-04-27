// Phase 8.4 — Operations Dashboard 최근 실패 N건 패널.
//
// 운영자가 장애를 보고 바로 고치는 흐름을 위해 최근 24h 내 FAILED pipeline_run
// 을 노드/원천(raw_object/inbound_envelope) 링크와 함께 노출.
import { AlertTriangle, ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { useRecentFailures } from "@/api/v2/operations";
import { Card, CardContent } from "@/components/ui/card";

function relativeKor(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const m = Math.round(diffMs / 60_000);
  if (m < 1) return "방금";
  if (m < 60) return `${m}분 전`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}시간 전`;
  const d = Math.round(h / 24);
  return `${d}일 전`;
}

export function RecentFailuresPanel() {
  const failures = useRecentFailures(10);

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1 text-sm font-semibold text-rose-600">
            <AlertTriangle className="h-3.5 w-3.5" />
            최근 실패 10건
          </h3>
          <span className="text-[10px] text-muted-foreground">
            24h · 30s 자동 갱신
          </span>
        </div>

        {failures.isLoading && (
          <p className="text-xs text-muted-foreground">불러오는 중…</p>
        )}
        {failures.isError && (
          <p className="text-xs text-rose-600">
            로드 실패: {(failures.error as Error).message}
          </p>
        )}
        {failures.data && failures.data.length === 0 && (
          <p className="text-xs text-muted-foreground">
            ✓ 최근 24시간 내 실패 건이 없습니다.
          </p>
        )}

        {failures.data && failures.data.length > 0 && (
          <ul className="divide-y divide-border">
            {failures.data.map((f) => (
              <li key={`${f.pipeline_run_id}-${f.run_date}`} className="py-1.5 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <Link
                    to={`/v2/operations/runs/${f.pipeline_run_id}?run_date=${f.run_date}`}
                    className="flex-1 truncate font-medium text-primary hover:underline"
                  >
                    {f.workflow_name ?? `workflow#${f.workflow_id}`}
                  </Link>
                  <span className="shrink-0 text-[10px] text-muted-foreground">
                    {relativeKor(f.started_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                  {f.failed_node_key && (
                    <span className="rounded bg-rose-100 px-1 py-0.5 font-mono text-rose-700">
                      {f.failed_node_type}:{f.failed_node_key}
                    </span>
                  )}
                  {f.raw_object_id && (
                    <Link
                      to={`/v2/raw-objects/${f.raw_object_id}`}
                      className="flex items-center gap-0.5 text-primary hover:underline"
                      title="원천 raw object"
                    >
                      <ExternalLink className="h-2.5 w-2.5" />
                      raw#{f.raw_object_id}
                    </Link>
                  )}
                  {f.inbound_envelope_id && (
                    <Link
                      to={`/v2/inbound-events/${f.inbound_envelope_id}`}
                      className="flex items-center gap-0.5 text-primary hover:underline"
                      title="원천 inbound envelope"
                    >
                      <ExternalLink className="h-2.5 w-2.5" />
                      env#{f.inbound_envelope_id}
                    </Link>
                  )}
                </div>
                {f.error_message && (
                  <p className="mt-0.5 truncate text-[10px] text-rose-700" title={f.error_message}>
                    {f.error_message}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
