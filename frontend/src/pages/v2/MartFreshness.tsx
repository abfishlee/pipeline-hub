import { Database, RefreshCw } from "lucide-react";
import { useFreshness } from "@/api/v2/operations";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

export function MartFreshness() {
  const freshness = useFreshness(60);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Mart Freshness</h2>
          <p className="max-w-4xl text-sm text-muted-foreground">
            서비스 마트가 최신 원천 데이터를 반영하고 있는지 확인하는 운영 화면입니다. 현재는
            inbound/source freshness를 기준으로 표시하고, 이후 mart table별 last refresh를 연결합니다.
          </p>
        </div>
        <Button variant="outline" onClick={() => freshness.refetch()}>
          <RefreshCw className="h-4 w-4" />
          새로고침
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <Thead>
              <Tr>
                <Th>Source / Channel</Th>
                <Th>Kind</Th>
                <Th>Last Received</Th>
                <Th>Freshness</Th>
                <Th>Service Mart Impact</Th>
              </Tr>
            </Thead>
            <Tbody>
              {freshness.isLoading && (
                <Tr>
                  <Td colSpan={5} className="text-center text-muted-foreground">
                    불러오는 중...
                  </Td>
                </Tr>
              )}
              {!freshness.isLoading && (freshness.data?.length ?? 0) === 0 && (
                <Tr>
                  <Td colSpan={5} className="text-center text-muted-foreground">
                    freshness를 판단할 inbound channel이 없습니다.
                  </Td>
                </Tr>
              )}
              {freshness.data?.map((row) => (
                <Tr key={row.channel_code}>
                  <Td>
                    <div className="font-medium">{row.channel_name ?? row.channel_code}</div>
                    <code className="text-xs text-muted-foreground">
                      {row.channel_code}
                    </code>
                  </Td>
                  <Td>{row.channel_kind}</Td>
                  <Td>
                    {row.last_received_at ? formatDateTime(row.last_received_at) : "-"}
                  </Td>
                  <Td>
                    <Badge variant={row.is_stale ? "warning" : "success"}>
                      {row.is_stale ? "STALE" : "FRESH"}
                    </Badge>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {row.minutes_since_last == null
                        ? "no event"
                        : `${row.minutes_since_last} min ago`}
                    </div>
                  </Td>
                  <Td className="text-sm text-muted-foreground">
                    <Database className="mr-1 inline h-3.5 w-3.5" />
                    agri_price mart 최신성 판단에 사용
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
