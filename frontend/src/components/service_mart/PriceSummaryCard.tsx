// Phase 8.4 — Service Mart 표준품목 카드 — 최저/최고/평균/할인폭 요약.
//
// 4 유통사 통합 가격을 한 줄로 보여줘서 "데이터가 실제 서비스에 어떻게 쓰이는지"
// 즉시 이해 가능. ServiceMartViewer 의 표 위에 sticky 로 배치.
import { TrendingDown, TrendingUp } from "lucide-react";
import { useMemo } from "react";
import type { ServicePriceRow } from "@/api/v2/service_mart";
import { Card, CardContent } from "@/components/ui/card";

interface Props {
  prices: ServicePriceRow[];
  stdProductName: string | null;
}

const fmt = (n: number) => new Intl.NumberFormat("ko-KR").format(Math.round(n));

export function PriceSummaryCard({ prices, stdProductName }: Props) {
  const stats = useMemo(() => {
    const effective: number[] = [];
    let promoCount = 0;
    let normalCount = 0;
    let stockOutCount = 0;
    let needsReviewCount = 0;
    let lastCollectedAt = "";
    for (const p of prices) {
      const promo = p.price_promo ? Number(p.price_promo) : NaN;
      const normal = p.price_normal ? Number(p.price_normal) : NaN;
      const eff = !isNaN(promo) && promo > 0 ? promo : !isNaN(normal) ? normal : NaN;
      if (!isNaN(eff) && eff > 0) effective.push(eff);
      if (p.price_promo && Number(p.price_promo) > 0) promoCount += 1;
      if (p.price_normal && Number(p.price_normal) > 0) normalCount += 1;
      if (p.stock_status === "OUT_OF_STOCK") stockOutCount += 1;
      if (p.needs_review) needsReviewCount += 1;
      if (p.collected_at > lastCollectedAt) lastCollectedAt = p.collected_at;
    }
    if (effective.length === 0) {
      return null;
    }
    effective.sort((a, b) => a - b);
    const min = effective[0];
    const max = effective[effective.length - 1];
    const avg = effective.reduce((s, v) => s + v, 0) / effective.length;
    const spreadPct = max > 0 ? Math.round(((max - min) / max) * 100) : 0;
    return {
      min,
      max,
      avg,
      spreadPct,
      promoCount,
      normalCount,
      stockOutCount,
      needsReviewCount,
      sampleCount: effective.length,
      lastCollectedAt,
    };
  }, [prices]);

  if (!stats) return null;

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold">
            가격 요약 — {stdProductName ?? "—"}
          </h3>
          <span className="text-[10px] text-muted-foreground">
            {stats.sampleCount}건 샘플 · 마지막 수집:{" "}
            {stats.lastCollectedAt
              ? new Date(stats.lastCollectedAt).toLocaleString("ko-KR")
              : "—"}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-2">
            <div className="flex items-center gap-1 text-[10px] font-semibold text-emerald-700">
              <TrendingDown className="h-3 w-3" />
              최저가
            </div>
            <div className="text-base font-semibold text-emerald-700">
              {fmt(stats.min)}원
            </div>
          </div>
          <div className="rounded-md border border-rose-200 bg-rose-50 p-2">
            <div className="flex items-center gap-1 text-[10px] font-semibold text-rose-700">
              <TrendingUp className="h-3 w-3" />
              최고가
            </div>
            <div className="text-base font-semibold text-rose-700">
              {fmt(stats.max)}원
            </div>
          </div>
          <div className="rounded-md border border-border bg-muted/30 p-2">
            <div className="text-[10px] font-semibold text-muted-foreground">평균</div>
            <div className="text-base font-semibold">{fmt(stats.avg)}원</div>
          </div>
          <div className="rounded-md border border-amber-200 bg-amber-50 p-2">
            <div className="text-[10px] font-semibold text-amber-700">
              가격 편차
            </div>
            <div className="text-base font-semibold text-amber-700">
              {stats.spreadPct}%
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px]">
          {stats.promoCount > 0 && (
            <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-700">
              할인 중 {stats.promoCount}건
            </span>
          )}
          {stats.stockOutCount > 0 && (
            <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-zinc-700">
              품절 {stats.stockOutCount}건
            </span>
          )}
          {stats.needsReviewCount > 0 && (
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">
              검수 필요 {stats.needsReviewCount}건
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
