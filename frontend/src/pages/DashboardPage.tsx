import { useJobs } from "@/api/jobs";
import { useSources } from "@/api/sources";
import { QuickStartCard } from "@/components/dashboard/QuickStartCard";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime, formatNumber } from "@/lib/format";

export function DashboardPage() {
  const sources = useSources({ limit: 100 });
  const today = todayIsoStart();
  const todayJobs = useJobs({ from: today, limit: 100 });
  const recentFailures = useJobs({ status: "FAILED", limit: 5 });

  const totalSources = sources.data?.length ?? 0;
  const activeSources =
    sources.data?.filter((s) => s.is_active).length ?? 0;
  const todayTotal = todayJobs.data?.length ?? 0;
  const todaySuccess =
    todayJobs.data?.filter((j) => j.status === "SUCCESS").length ?? 0;
  const todayFailed =
    todayJobs.data?.filter((j) => j.status === "FAILED").length ?? 0;

  return (
    <div className="space-y-6">
      <QuickStartCard />
      <div className="grid gap-4 md:grid-cols-4">
        <KpiCard label="활성 소스" value={`${activeSources} / ${totalSources}`} />
        <KpiCard label="오늘 수집 작업" value={formatNumber(todayTotal)} />
        <KpiCard
          label="오늘 성공"
          value={formatNumber(todaySuccess)}
          tone="success"
        />
        <KpiCard
          label="오늘 실패"
          value={formatNumber(todayFailed)}
          tone={todayFailed > 0 ? "destructive" : "muted"}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>최근 실패 5건</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {recentFailures.isLoading && <div className="p-4 text-sm">불러오는 중...</div>}
          {recentFailures.data && recentFailures.data.length === 0 && (
            <div className="p-4 text-sm text-muted-foreground">실패 작업 없음</div>
          )}
          {recentFailures.data && recentFailures.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>job_id</Th>
                  <Th>source_id</Th>
                  <Th>상태</Th>
                  <Th>오류 메시지</Th>
                  <Th>시각</Th>
                </Tr>
              </Thead>
              <Tbody>
                {recentFailures.data.map((j) => (
                  <Tr key={j.job_id}>
                    <Td className="font-mono">{j.job_id}</Td>
                    <Td className="font-mono">{j.source_id}</Td>
                    <Td>
                      <StatusBadge status={j.status} />
                    </Td>
                    <Td className="max-w-md truncate text-xs text-muted-foreground">
                      {j.error_message ?? "-"}
                    </Td>
                    <Td className="text-xs">{formatDateTime(j.created_at)}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function KpiCard({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string;
  tone?: "default" | "success" | "destructive" | "muted";
}) {
  const toneClass = {
    default: "text-foreground",
    success: "text-emerald-600",
    destructive: "text-destructive",
    muted: "text-muted-foreground",
  }[tone];
  return (
    <Card>
      <CardContent className="space-y-1 p-5">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className={`text-2xl font-semibold ${toneClass}`}>{value}</div>
      </CardContent>
    </Card>
  );
}

function todayIsoStart(): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  return d.toISOString();
}
