// Phase 8.5 — Operations Dashboard Real Operation 카드 4종.
//
// SlaLagCard / StaleChannelsPanel / DispatcherHealthCard / ProviderCostCard.
import {
  Activity,
  CheckCircle2,
  DollarSign,
  Gauge,
  Inbox,
  WifiOff,
} from "lucide-react";
import {
  useDispatcherHealth,
  useFreshness,
  useProviderUsage,
  useSlaLag,
} from "@/api/v2/operations";
import { Card, CardContent } from "@/components/ui/card";

const fmtNum = (n: number) => new Intl.NumberFormat("ko-KR").format(Math.round(n));
const fmtSec = (s: number | null) => (s == null ? "—" : `${s.toFixed(1)}s`);

// ============================================================================
// SLA Lag Card
// ============================================================================
export function SlaLagCard() {
  const q = useSlaLag();
  const d = q.data;
  const p95 = d?.p95_seconds;
  let tone = "border-border bg-muted/30 text-foreground";
  let label = "—";
  if (p95 != null) {
    if (p95 <= 60) {
      tone = "border-emerald-200 bg-emerald-50 text-emerald-700";
      label = "정상";
    } else if (p95 <= 180) {
      tone = "border-amber-200 bg-amber-50 text-amber-700";
      label = "주의";
    } else {
      tone = "border-rose-200 bg-rose-50 text-rose-700";
      label = "초과";
    }
  }
  return (
    <Card className={tone}>
      <CardContent className="space-y-1 p-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1 text-xs font-semibold uppercase">
            <Gauge className="h-3.5 w-3.5" />
            SLA Lag (수집→적재)
          </h3>
          <span className="rounded px-1.5 py-0.5 text-[10px] font-semibold">
            {label}
          </span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold">{fmtSec(p95 ?? null)}</span>
          <span className="text-[10px]">p95 (target ≤ {d?.threshold_seconds ?? 60}s)</span>
        </div>
        <div className="text-[10px]">
          p50 {fmtSec(d?.p50_seconds ?? null)} · p99 {fmtSec(d?.p99_seconds ?? null)} ·
          max {fmtSec(d?.max_seconds ?? null)}
          {(d?.sample_count ?? 0) > 0 && (
            <> · {d?.sample_count} samples · 임계 초과 {d?.breached_count}건</>
          )}
        </div>
        {(d?.sample_count ?? 0) === 0 && (
          <p className="text-[10px] opacity-70">
            inbound→완료 lag 측정 가능한 샘플 없음 (24h)
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// Stale Channels Panel
// ============================================================================
export function StaleChannelsPanel() {
  const q = useFreshness(60);
  const stale = (q.data ?? []).filter((c) => c.is_stale);
  const fresh = (q.data ?? []).filter((c) => !c.is_stale);

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1 text-sm font-semibold">
            <Inbox className="h-3.5 w-3.5 text-primary" />
            채널 데이터 신선도
          </h3>
          <span className="text-[10px] text-muted-foreground">
            {fresh.length} 정상 · {stale.length} stale (60min+)
          </span>
        </div>
        {(q.data ?? []).length === 0 && (
          <p className="text-xs text-muted-foreground">
            등록된 PUBLISHED inbound 채널이 없습니다.
          </p>
        )}
        {stale.length > 0 && (
          <ul className="space-y-1">
            {stale.map((c) => (
              <li
                key={c.channel_code}
                className="flex items-center gap-2 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-xs"
              >
                <WifiOff className="h-3 w-3 text-rose-600" />
                <span className="font-mono font-semibold text-rose-700">
                  {c.channel_code}
                </span>
                <span className="text-rose-700">
                  {c.channel_name ?? c.channel_kind}
                </span>
                <span className="ml-auto text-[10px] text-rose-700">
                  {c.minutes_since_last ?? "—"}분 전
                </span>
              </li>
            ))}
          </ul>
        )}
        {fresh.length > 0 && (
          <details className="text-[10px] text-muted-foreground">
            <summary className="cursor-pointer">정상 채널 {fresh.length}건 펼치기</summary>
            <ul className="mt-1 space-y-0.5">
              {fresh.map((c) => (
                <li key={c.channel_code} className="flex items-center gap-2">
                  <CheckCircle2 className="h-2.5 w-2.5 text-emerald-600" />
                  <span className="font-mono">{c.channel_code}</span>
                  <span className="ml-auto">{c.minutes_since_last ?? "—"}분 전</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// Dispatcher Health Card
// ============================================================================
export function DispatcherHealthCard() {
  const q = useDispatcherHealth();
  const d = q.data;
  const lastAt = d?.last_dispatch_attempt_at
    ? new Date(d.last_dispatch_attempt_at)
    : null;
  const ageSec = lastAt ? (Date.now() - lastAt.getTime()) / 1000 : null;
  const stale = ageSec != null && ageSec > (d?.poll_interval_seconds ?? 5) * 6;
  const tone = !d
    ? "border-border bg-muted/30"
    : stale
      ? "border-rose-200 bg-rose-50"
      : "border-emerald-200 bg-emerald-50";
  return (
    <Card className={tone}>
      <CardContent className="space-y-1 p-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1 text-xs font-semibold uppercase">
            <Activity className="h-3.5 w-3.5" />
            Auto Dispatcher
          </h3>
          <span className="text-[10px] font-semibold">
            {!d ? "—" : stale ? "STALE" : "RUNNING"}
          </span>
        </div>
        <div className="text-[11px]">
          <span>대기 envelope: </span>
          <span className="font-semibold">{fmtNum(d?.pending_envelopes ?? 0)}</span>
        </div>
        <div className="text-[10px] text-muted-foreground">
          last attempt:{" "}
          {ageSec != null ? `${ageSec.toFixed(0)}s 전` : "—"} · 직전 처리{" "}
          {fmtNum(d?.last_dispatched_count ?? 0)} · poll {d?.poll_interval_seconds ?? 5}s
        </div>
      </CardContent>
    </Card>
  );
}

// ============================================================================
// Provider Cost Card
// ============================================================================
export function ProviderCostCard() {
  const q = useProviderUsage();
  const rows = q.data ?? [];
  const totalCost = rows.reduce((s, r) => s + (r.cost_estimate_24h || 0), 0);
  const totalReq = rows.reduce((s, r) => s + r.request_count_24h, 0);
  const totalErr = rows.reduce((s, r) => s + r.error_count_24h, 0);
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1 text-sm font-semibold">
            <DollarSign className="h-3.5 w-3.5 text-primary" />
            Provider 호출/비용 (24h)
          </h3>
          <span className="text-[10px] text-muted-foreground">
            {fmtNum(totalReq)}건 · 오류 {fmtNum(totalErr)}건 · ₩{fmtNum(totalCost)}
          </span>
        </div>
        {rows.length === 0 && (
          <p className="text-xs text-muted-foreground">
            24시간 내 외부 provider 호출 없음.
          </p>
        )}
        {rows.length > 0 && (
          <table className="w-full text-xs">
            <thead className="text-[10px] text-muted-foreground">
              <tr>
                <th className="text-left">provider</th>
                <th className="text-right">호출</th>
                <th className="text-right">오류</th>
                <th className="text-right">평균 ms</th>
                <th className="text-right">비용</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const errRate =
                  r.request_count_24h > 0
                    ? (r.error_count_24h / r.request_count_24h) * 100
                    : 0;
                return (
                  <tr key={r.provider_code} className="border-t border-border">
                    <td className="py-1">
                      <span className="font-mono">{r.provider_code}</span>
                      {r.provider_kind && (
                        <span className="ml-1 text-[10px] text-muted-foreground">
                          {r.provider_kind}
                        </span>
                      )}
                    </td>
                    <td className="text-right">{fmtNum(r.request_count_24h)}</td>
                    <td
                      className={`text-right ${
                        errRate > 5 ? "text-rose-600" : ""
                      }`}
                    >
                      {fmtNum(r.error_count_24h)}
                    </td>
                    <td className="text-right">
                      {r.avg_duration_ms != null ? r.avg_duration_ms.toFixed(0) : "—"}
                    </td>
                    <td className="text-right font-semibold">
                      ₩{fmtNum(r.cost_estimate_24h)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
