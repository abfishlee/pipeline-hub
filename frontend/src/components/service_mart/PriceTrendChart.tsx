// Phase 8.2 — Service Mart 가격 변동 추이 차트.
//
// 선택된 표준 품목의 4 유통사 7일치 가격 추이 라인 차트.
import { useMemo } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ServicePriceRow } from "@/api/v2/service_mart";
import { Card, CardContent } from "@/components/ui/card";

const RETAILER_LABELS: Record<string, string> = {
  emart: "이마트",
  homeplus: "홈플러스",
  lottemart: "롯데마트",
  hanaro: "하나로마트",
};

const RETAILER_COLORS: Record<string, string> = {
  emart: "#eab308",
  homeplus: "#ef4444",
  lottemart: "#e11d48",
  hanaro: "#16a34a",
};

interface PriceTrendChartProps {
  prices: ServicePriceRow[];
  stdProductName: string | null;
}

export function PriceTrendChart({ prices, stdProductName }: PriceTrendChartProps) {
  const data = useMemo(() => {
    if (!prices.length) return [];
    // 일자별 (collected_at 의 YYYY-MM-DD) 유통사별 평균가 산출.
    const byDay = new Map<string, Record<string, number | string>>();
    for (const p of prices) {
      const day = p.collected_at.slice(0, 10);
      const effective = p.price_promo
        ? Number(p.price_promo)
        : p.price_normal
          ? Number(p.price_normal)
          : null;
      if (effective == null || effective <= 0) continue;
      let row = byDay.get(day);
      if (!row) {
        row = { day };
        byDay.set(day, row);
      }
      row[p.retailer_code] = effective;
    }
    return Array.from(byDay.values()).sort((a, b) =>
      String(a.day).localeCompare(String(b.day)),
    );
  }, [prices]);

  if (data.length === 0) return null;

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold">
            가격 변동 추이 — {stdProductName ?? "—"}
          </h3>
          <span className="text-xs text-muted-foreground">
            {data.length} 일치
          </span>
        </div>
        <div style={{ width: "100%", height: 220 }}>
          <ResponsiveContainer>
            <LineChart data={data} margin={{ top: 10, right: 10, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis
                dataKey="day"
                tick={{ fontSize: 10 }}
                tickFormatter={(v) => String(v).slice(5)}
              />
              <YAxis
                tick={{ fontSize: 10 }}
                tickFormatter={(v) =>
                  new Intl.NumberFormat("ko-KR").format(v as number)
                }
              />
              <Tooltip
                formatter={(value) => {
                  const n = typeof value === "number" ? value : Number(value);
                  return isNaN(n)
                    ? String(value)
                    : new Intl.NumberFormat("ko-KR").format(n) + "원";
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {Object.keys(RETAILER_LABELS).map((code) => (
                <Line
                  key={code}
                  type="monotone"
                  dataKey={code}
                  stroke={RETAILER_COLORS[code]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  name={RETAILER_LABELS[code]}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="text-[10px] text-muted-foreground">
          ※ 행사가가 있으면 행사가, 없으면 정상가 기준. 일별 평균.
        </p>
      </CardContent>
    </Card>
  );
}
