import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useInboundEvents } from "@/api/v2/operations";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

const STATUS_VARIANT: Record<
  string,
  "default" | "secondary" | "success" | "warning" | "muted" | "destructive"
> = {
  RECEIVED: "warning",
  PROCESSING: "default",
  DONE: "success",
  FAILED: "destructive",
};

function formatBytes(bytes: number) {
  if (bytes >= 1024 * 1024) return `${Math.round(bytes / 1024 / 1024)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

export function InboundInbox() {
  const [status, setStatus] = useState("");
  const events = useInboundEvents({ status, limit: 200 });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Inbound Inbox</h2>
          <p className="max-w-4xl text-sm text-muted-foreground">
            외부에서 push된 원본 envelope를 확인합니다. 여기서 수신 여부, 처리 상태,
            연결된 Job run, 실패 사유를 추적합니다.
          </p>
        </div>
        <Button variant="outline" onClick={() => events.refetch()}>
          <RefreshCw className="h-4 w-4" />
          새로고침
        </Button>
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <span className="text-sm text-muted-foreground">status</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="h-9 rounded-md border bg-background px-3 text-sm"
          >
            <option value="">전체</option>
            <option value="RECEIVED">RECEIVED</option>
            <option value="PROCESSING">PROCESSING</option>
            <option value="DONE">DONE</option>
            <option value="FAILED">FAILED</option>
          </select>
          <Link to="/v2/inbound-channels/designer" className="ml-auto text-sm text-primary underline">
            채널 설정으로 이동
          </Link>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <Thead>
              <Tr>
                <Th>Envelope</Th>
                <Th>Channel</Th>
                <Th>Payload</Th>
                <Th>Status</Th>
                <Th>Job Run</Th>
                <Th>Processed</Th>
              </Tr>
            </Thead>
            <Tbody>
              {events.isLoading && (
                <Tr>
                  <Td colSpan={6} className="text-center text-muted-foreground">
                    불러오는 중...
                  </Td>
                </Tr>
              )}
              {!events.isLoading && (events.data?.length ?? 0) === 0 && (
                <Tr>
                  <Td colSpan={6} className="text-center text-muted-foreground">
                    수신된 inbound envelope가 없습니다.
                  </Td>
                </Tr>
              )}
              {events.data?.map((e) => (
                <Tr key={e.envelope_id}>
                  <Td>
                    <div className="font-mono">#{e.envelope_id}</div>
                    <div className="text-xs text-muted-foreground">
                      {formatDateTime(e.received_at)}
                    </div>
                  </Td>
                  <Td>
                    <code className="text-xs">{e.channel_code}</code>
                    <div className="text-xs text-muted-foreground">
                      {e.domain_code ?? "-"}
                    </div>
                  </Td>
                  <Td className="text-xs">
                    <div>{e.content_type}</div>
                    <div className="text-muted-foreground">
                      {formatBytes(e.payload_size_bytes)} ·{" "}
                      {e.has_inline_payload ? "inline JSON" : e.payload_object_key ?? "object"}
                    </div>
                  </Td>
                  <Td>
                    <Badge variant={STATUS_VARIANT[e.status] ?? "muted"}>
                      {e.status}
                    </Badge>
                    {e.error_message && (
                      <div className="mt-1 max-w-xs truncate text-xs text-destructive">
                        {e.error_message}
                      </div>
                    )}
                  </Td>
                  <Td>
                    {e.workflow_run_id ? (
                      <Link
                        to={`/pipelines/runs/${e.workflow_run_id}`}
                        className="text-primary underline"
                      >
                        run #{e.workflow_run_id}
                      </Link>
                    ) : (
                      <span className="text-xs text-muted-foreground">-</span>
                    )}
                  </Td>
                  <Td className="text-xs text-muted-foreground">
                    {e.processed_at ? formatDateTime(e.processed_at) : "-"}
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
