import { useState } from "react";
import {
  type SecurityEventKind,
  type SecurityEventOut,
  type SecurityEventSeverity,
  useSecurityEvents,
} from "@/api/security_events";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

const KINDS: SecurityEventKind[] = [
  "IP_MULTI_KEY",
  "KEY_HIGH_4XX",
  "IP_BURST",
  "TLS_FAIL",
  "OTHER",
];
const SEVERITIES: SecurityEventSeverity[] = ["INFO", "WARN", "ERROR", "CRITICAL"];

const SEVERITY_VARIANT: Record<
  SecurityEventSeverity,
  "default" | "muted" | "destructive" | "success"
> = {
  INFO: "muted",
  WARN: "default",
  ERROR: "destructive",
  CRITICAL: "destructive",
};

export function SecurityEventsPage() {
  const [kind, setKind] = useState<SecurityEventKind | "">("");
  const [severity, setSeverity] = useState<SecurityEventSeverity | "">("");
  const [detail, setDetail] = useState<SecurityEventOut | null>(null);
  const events = useSecurityEvents({
    kind: kind || null,
    severity: severity || null,
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
          <span className="text-muted-foreground">kind:</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as SecurityEventKind | "")}
            className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">(전체)</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <span className="text-muted-foreground">severity:</span>
          <select
            value={severity}
            onChange={(e) =>
              setSeverity(e.target.value as SecurityEventSeverity | "")
            }
            className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">(전체)</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {(kind || severity) && (
            <button
              type="button"
              className="text-xs text-muted-foreground underline"
              onClick={() => {
                setKind("");
                setSeverity("");
              }}
            >
              필터 초기화
            </button>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <Thead>
              <Tr>
                <Th>ID</Th>
                <Th>kind</Th>
                <Th>severity</Th>
                <Th>ip</Th>
                <Th>api_key_id</Th>
                <Th>occurred_at</Th>
                <Th></Th>
              </Tr>
            </Thead>
            <Tbody>
              {events.isLoading && (
                <Tr>
                  <Td colSpan={7} className="text-center text-muted-foreground">
                    로딩 중…
                  </Td>
                </Tr>
              )}
              {!events.isLoading && (events.data?.length ?? 0) === 0 && (
                <Tr>
                  <Td colSpan={7} className="text-center text-muted-foreground">
                    이벤트가 없습니다.
                  </Td>
                </Tr>
              )}
              {events.data?.map((e) => (
                <Tr key={e.event_id}>
                  <Td className="font-mono text-xs">{e.event_id}</Td>
                  <Td className="font-mono">{e.kind}</Td>
                  <Td>
                    <Badge variant={SEVERITY_VARIANT[e.severity]}>
                      {e.severity}
                    </Badge>
                  </Td>
                  <Td className="font-mono text-xs">{e.ip_addr ?? "-"}</Td>
                  <Td className="font-mono text-xs">{e.api_key_id ?? "-"}</Td>
                  <Td className="text-xs">{formatDateTime(e.occurred_at)}</Td>
                  <Td>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setDetail(e)}
                    >
                      상세
                    </Button>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardContent>
      </Card>

      {detail && (
        <DetailModal event={detail} onClose={() => setDetail(null)} />
      )}
    </div>
  );
}

function DetailModal({
  event,
  onClose,
}: {
  event: SecurityEventOut;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-lg bg-background p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">
            보안 이벤트 #{event.event_id}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
          >
            ×
          </button>
        </div>
        <ul className="space-y-1 text-sm">
          <li>
            kind: <code className="font-mono">{event.kind}</code>
          </li>
          <li>severity: {event.severity}</li>
          <li>
            ip: <code className="font-mono">{event.ip_addr ?? "-"}</code>
          </li>
          <li>api_key_id: {event.api_key_id ?? "-"}</li>
          <li>occurred_at: {formatDateTime(event.occurred_at)}</li>
          <li>
            user_agent: <code className="text-xs">{event.user_agent ?? "-"}</code>
          </li>
        </ul>
        <pre className="mt-4 overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(event.details_json, null, 2)}
        </pre>
      </div>
    </div>
  );
}
