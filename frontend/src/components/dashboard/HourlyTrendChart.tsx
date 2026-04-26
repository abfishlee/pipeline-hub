// Phase 8.2 — Operations Dashboard 24h 시간별 추이 차트.
import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { HourlyTrendBucket } from "@/api/v2/operations";
import { Card, CardContent } from "@/components/ui/card";

interface HourlyTrendChartProps {
  data: HourlyTrendBucket[] | undefined;
}

export function HourlyTrendChart({ data }: HourlyTrendChartProps) {
  const chartData = useMemo(() => {
    if (!data) return [];
    return data.map((b) => ({
      hour: new Date(b.bucket_hour).toLocaleString("ko-KR", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
      }),
      success: b.success,
      failed: b.failed,
    }));
  }, [data]);

  if (!chartData.length) {
    return (
      <Card>
        <CardContent className="p-4 text-xs text-muted-foreground">
          24시간 내 실행 이력이 없습니다.
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <h3 className="text-sm font-semibold">24h 시간별 실행 추이</h3>
        <div style={{ width: "100%", height: 180 }}>
          <ResponsiveContainer>
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="hour" tick={{ fontSize: 9 }} />
              <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="success" stackId="a" fill="#16a34a" name="success" />
              <Bar dataKey="failed" stackId="a" fill="#dc2626" name="failed" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}
