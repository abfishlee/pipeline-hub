// Phase 8.1 — 표준품목 선택 시 4 유통사 가격 비교 카드.
//
// 사용자 § 8 — Service Mart Viewer 강화: 상품별 최저가/평균가/유통사별 가격 비교.
import { TrendingDown, TrendingUp } from "lucide-react";
import { useMemo } from "react";
import type { ServicePriceRow } from "@/api/v2/service_mart";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";

const RETAILER_LABELS: Record<string, string> = {
  emart: "이마트",
  homeplus: "홈플러스",
  lottemart: "롯데마트",
  hanaro: "하나로마트",
};

interface PriceCompareCardProps {
  prices: ServicePriceRow[];
  stdProductName: string | null;
}

export function PriceCompareCard({ prices, stdProductName }: PriceCompareCardProps) {
  const stats = useMemo(() => {
    if (!prices.length) return null;

    // 유통사별 최저가 (행사가 우선, 없으면 정상가)
    const byRetailer = new Map<
      string,
      { effective: number; normal: number | null; promo: number | null; row: ServicePriceRow }
    >();
    for (const p of prices) {
      const normal = p.price_normal ? Number(p.price_normal) : null;
      const promo = p.price_promo ? Number(p.price_promo) : null;
      const effective = promo ?? normal ?? 0;
      if (effective <= 0) continue;
      const existing = byRetailer.get(p.retailer_code);
      if (!existing || effective < existing.effective) {
        byRetailer.set(p.retailer_code, { effective, normal, promo, row: p });
      }
    }

    if (byRetailer.size === 0) return null;

    const entries = Array.from(byRetailer.entries()).sort(
      (a, b) => a[1].effective - b[1].effective,
    );
    const min = entries[0][1].effective;
    const max = entries[entries.length - 1][1].effective;
    const avg =
      entries.reduce((sum, [, v]) => sum + v.effective, 0) / entries.length;
    const promoCount = entries.filter(([, v]) => v.promo !== null).length;

    return { entries, min, max, avg, promoCount };
  }, [prices]);

  if (!stats) {
    return null;
  }

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <h3 className="text-sm font-semibold">
            가격 비교 — {stdProductName ?? "—"}
          </h3>
          <span className="text-xs text-muted-foreground">
            {stats.entries.length} 유통사 · 행사 {stats.promoCount}건
          </span>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-md border border-green-300 bg-green-50 p-3">
            <div className="flex items-center gap-1 text-xs font-semibold text-green-700">
              <TrendingDown className="h-3.5 w-3.5" />
              최저가
            </div>
            <div className="mt-1 text-xl font-semibold text-green-700">
              {new Intl.NumberFormat("ko-KR").format(stats.min)}원
            </div>
            <div className="mt-0.5 text-[10px] text-green-700/80">
              {RETAILER_LABELS[stats.entries[0][0]] ?? stats.entries[0][0]}
            </div>
          </div>
          <div className="rounded-md border border-border p-3">
            <div className="text-xs font-semibold text-muted-foreground">
              평균가
            </div>
            <div className="mt-1 text-xl font-semibold">
              {new Intl.NumberFormat("ko-KR").format(Math.round(stats.avg))}원
            </div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">
              {stats.entries.length} 유통사 평균
            </div>
          </div>
          <div className="rounded-md border border-rose-200 bg-rose-50 p-3">
            <div className="flex items-center gap-1 text-xs font-semibold text-rose-700">
              <TrendingUp className="h-3.5 w-3.5" />
              최고가
            </div>
            <div className="mt-1 text-xl font-semibold text-rose-700">
              {new Intl.NumberFormat("ko-KR").format(stats.max)}원
            </div>
            <div className="mt-0.5 text-[10px] text-rose-700/80">
              {RETAILER_LABELS[
                stats.entries[stats.entries.length - 1][0]
              ] ?? stats.entries[stats.entries.length - 1][0]}
            </div>
          </div>
        </div>

        <div className="space-y-1">
          {stats.entries.map(([code, v]) => {
            const range = stats.max - stats.min;
            const offset = range > 0 ? ((v.effective - stats.min) / range) * 100 : 0;
            const isMin = v.effective === stats.min;
            return (
              <div
                key={code}
                className="flex items-center gap-2 rounded-md border border-border p-2 text-xs"
              >
                <div className="w-24 font-semibold">
                  {RETAILER_LABELS[code] ?? code}
                </div>
                <div className="flex-1">
                  <div className="relative h-2 overflow-hidden rounded bg-muted">
                    <div
                      className={cn(
                        "absolute h-full",
                        isMin ? "bg-green-500" : "bg-blue-400",
                      )}
                      style={{ width: `${100 - offset * 0.6}%` }}
                    />
                  </div>
                </div>
                <div className="w-32 text-right">
                  {v.promo && v.normal && v.normal > v.promo ? (
                    <>
                      <span className="text-muted-foreground line-through">
                        {new Intl.NumberFormat("ko-KR").format(v.normal)}
                      </span>{" "}
                      <span className="font-semibold text-rose-600">
                        {new Intl.NumberFormat("ko-KR").format(v.promo)}원
                      </span>
                    </>
                  ) : (
                    <span className={cn(isMin && "font-semibold text-green-700")}>
                      {new Intl.NumberFormat("ko-KR").format(v.effective)}원
                    </span>
                  )}
                </div>
                <div className="w-32 truncate text-[10px] text-muted-foreground">
                  {v.row.product_name}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
