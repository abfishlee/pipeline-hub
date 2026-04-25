import { Download, ExternalLink } from "lucide-react";
import { useState } from "react";
import {
  type ObjectType,
  type RawObjectSummary,
  type RawStatus,
  useRawObjectDetail,
  useRawObjects,
} from "@/api/raw_objects";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

const OBJECT_TYPES: ObjectType[] = [
  "JSON",
  "XML",
  "CSV",
  "HTML",
  "PDF",
  "IMAGE",
  "DB_ROW",
  "RECEIPT_IMAGE",
];
const STATUSES: RawStatus[] = ["RECEIVED", "PROCESSED", "FAILED", "DISCARDED"];

export function RawObjectsPage() {
  const [sourceIdInput, setSourceIdInput] = useState("");
  const [status, setStatus] = useState<RawStatus | "">("");
  const [objectType, setObjectType] = useState<ObjectType | "">("");
  const [page, setPage] = useState(0);
  const limit = 20;

  const sourceId = sourceIdInput.trim()
    ? Number(sourceIdInput.trim())
    : undefined;

  const list = useRawObjects({
    source_id: Number.isFinite(sourceId) ? sourceId : undefined,
    status: status || undefined,
    object_type: objectType || undefined,
    limit,
    offset: page * limit,
  });

  const [selected, setSelected] = useState<RawObjectSummary | null>(null);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <Filter label="source_id">
            <Input
              type="number"
              min={1}
              className="w-32"
              value={sourceIdInput}
              onChange={(e) => {
                setSourceIdInput(e.target.value);
                setPage(0);
              }}
            />
          </Filter>
          <Filter label="status">
            <select
              className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as RawStatus | "");
                setPage(0);
              }}
            >
              <option value="">(전체)</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Filter>
          <Filter label="object_type">
            <select
              className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={objectType}
              onChange={(e) => {
                setObjectType(e.target.value as ObjectType | "");
                setPage(0);
              }}
            >
              <option value="">(전체)</option>
              {OBJECT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Filter>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              이전
            </Button>
            <span className="text-sm text-muted-foreground">
              page {page + 1}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={(list.data?.length ?? 0) < limit}
              onClick={() => setPage((p) => p + 1)}
            >
              다음
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {list.isLoading && <div className="p-4 text-sm">불러오는 중...</div>}
          {list.data && list.data.length === 0 && (
            <div className="p-4 text-sm text-muted-foreground">결과 없음</div>
          )}
          {list.data && list.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>raw_object_id</Th>
                  <Th>source_id</Th>
                  <Th>type</Th>
                  <Th>status</Th>
                  <Th>저장</Th>
                  <Th>수신 시각</Th>
                  <Th></Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.data.map((r) => (
                  <Tr key={r.raw_object_id}>
                    <Td className="font-mono">{r.raw_object_id}</Td>
                    <Td className="font-mono">{r.source_id}</Td>
                    <Td>
                      <Badge variant="secondary">{r.object_type}</Badge>
                    </Td>
                    <Td>
                      <StatusBadge status={r.status} />
                    </Td>
                    <Td>
                      {r.has_inline_payload && (
                        <Badge variant="default">inline</Badge>
                      )}
                      {r.object_uri_present && (
                        <Badge variant="muted">storage</Badge>
                      )}
                    </Td>
                    <Td className="text-xs">{formatDateTime(r.received_at)}</Td>
                    <Td>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setSelected(r)}
                      >
                        상세
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <DetailDialog
        summary={selected}
        onOpenChange={(o) => !o && setSelected(null)}
      />
    </div>
  );
}

function DetailDialog({
  summary,
  onOpenChange,
}: {
  summary: RawObjectSummary | null;
  onOpenChange: (open: boolean) => void;
}) {
  const detail = useRawObjectDetail(
    summary?.raw_object_id ?? null,
    summary?.partition_date,
  );

  return (
    <Dialog open={summary != null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            원천 데이터 — raw_object_id {summary?.raw_object_id}
          </DialogTitle>
        </DialogHeader>
        {detail.isLoading && <div className="text-sm">불러오는 중...</div>}
        {detail.data && (
          <div className="space-y-4 text-sm">
            <KV label="source_id">{detail.data.source_id}</KV>
            <KV label="object_type">{detail.data.object_type}</KV>
            <KV label="status">{detail.data.status}</KV>
            <KV label="content_hash">
              <code className="break-all text-xs">{detail.data.content_hash}</code>
            </KV>
            <KV label="idempotency_key">
              {detail.data.idempotency_key ?? "-"}
            </KV>
            <KV label="partition_date">{detail.data.partition_date}</KV>
            {detail.data.payload_json && (
              <div>
                <div className="mb-1 text-xs font-medium text-muted-foreground">
                  payload_json (inline)
                </div>
                <pre className="max-h-80 overflow-auto rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(detail.data.payload_json, null, 2)}
                </pre>
              </div>
            )}
            {detail.data.object_uri && (
              <div>
                <div className="mb-1 text-xs font-medium text-muted-foreground">
                  object_uri
                </div>
                <code className="break-all text-xs">
                  {detail.data.object_uri}
                </code>
                {detail.data.download_url && (
                  <div className="mt-2 flex gap-2">
                    <a
                      href={detail.data.download_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <Button variant="outline" size="sm">
                        <Download className="h-4 w-4" />
                        다운로드 (5분 유효)
                      </Button>
                    </a>
                    <a
                      href={detail.data.download_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <Button variant="ghost" size="sm">
                        <ExternalLink className="h-4 w-4" />
                        새 창
                      </Button>
                    </a>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function KV({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[140px_1fr] items-baseline gap-2">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div>{children}</div>
    </div>
  );
}

function Filter({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}
