import { useState } from "react";
import { toast } from "sonner";
import {
  type DeadLetter,
  useDeadLetters,
  useReplayDeadLetter,
} from "@/api/dead_letters";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

export function DeadLetterQueue() {
  const [originFilter, setOriginFilter] = useState("");
  const [replayed, setReplayed] = useState(false);
  const [selected, setSelected] = useState<DeadLetter | null>(null);

  const dlq = useDeadLetters({
    origin: originFilter.trim() || undefined,
    replayed,
    limit: 50,
  });
  const replay = useReplayDeadLetter();

  const handleReplay = async (dlId: number) => {
    try {
      const result = await replay.mutateAsync(dlId);
      toast.success(`재발송 완료 — ${result.origin}`, {
        description: `message_id: ${result.enqueued_message_id ?? "(unknown)"}`,
      });
      setSelected(null);
    } catch (err) {
      toast.error("재발송 실패", { description: String(err) });
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">origin</label>
            <Input
              placeholder="actor 이름 (예: process_ocr_event)"
              className="w-72"
              value={originFilter}
              onChange={(e) => setOriginFilter(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="replayed-toggle"
              checked={replayed}
              onChange={(e) => setReplayed(e.target.checked)}
            />
            <label htmlFor="replayed-toggle" className="text-sm">
              재처리 완료 포함
            </label>
          </div>
          <Button variant="outline" size="sm" onClick={() => dlq.refetch()}>
            새로고침
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <Thead>
              <Tr>
                <Th>ID</Th>
                <Th>origin (actor)</Th>
                <Th>error</Th>
                <Th>실패 시각</Th>
                <Th>재처리</Th>
                <Th></Th>
              </Tr>
            </Thead>
            <Tbody>
              {dlq.isLoading && (
                <Tr>
                  <Td colSpan={6} className="text-center text-muted-foreground">
                    로딩 중…
                  </Td>
                </Tr>
              )}
              {!dlq.isLoading && (dlq.data?.length ?? 0) === 0 && (
                <Tr>
                  <Td colSpan={6} className="text-center text-muted-foreground">
                    Dead Letter 가 없습니다. (시스템 정상)
                  </Td>
                </Tr>
              )}
              {dlq.data?.map((row) => (
                <Tr key={row.dl_id}>
                  <Td className="font-mono">#{row.dl_id}</Td>
                  <Td className="font-mono text-xs">{row.origin}</Td>
                  <Td className="max-w-[400px] truncate text-xs text-destructive">
                    {row.error_message ?? "(no message)"}
                  </Td>
                  <Td className="text-xs">{formatDateTime(row.failed_at)}</Td>
                  <Td className="text-xs">
                    {row.replayed_at ? formatDateTime(row.replayed_at) : "—"}
                  </Td>
                  <Td>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setSelected(row)}
                      >
                        상세
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => handleReplay(row.dl_id)}
                        disabled={replay.isPending || row.replayed_at !== null}
                      >
                        재발송
                      </Button>
                    </div>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardContent>
      </Card>

      <Dialog
        open={selected !== null}
        onOpenChange={(open) => !open && setSelected(null)}
      >
        <DialogContent className="max-w-3xl">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle>
                  Dead Letter #{selected.dl_id} — {selected.origin}
                </DialogTitle>
                <DialogDescription>
                  failed at {formatDateTime(selected.failed_at)}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-3 text-sm">
                <div>
                  <div className="mb-1 text-xs text-muted-foreground">
                    error_message
                  </div>
                  <pre className="rounded-md bg-secondary p-2 text-xs text-destructive">
                    {selected.error_message ?? "(empty)"}
                  </pre>
                </div>
                <div>
                  <div className="mb-1 text-xs text-muted-foreground">
                    payload (actor args / kwargs)
                  </div>
                  <pre className="max-h-40 overflow-auto rounded-md bg-secondary p-2 text-xs">
                    {JSON.stringify(selected.payload_json, null, 2)}
                  </pre>
                </div>
                <div>
                  <div className="mb-1 text-xs text-muted-foreground">
                    stack_trace
                  </div>
                  <pre className="max-h-64 overflow-auto rounded-md bg-secondary p-2 text-xs">
                    {selected.stack_trace ?? "(no trace)"}
                  </pre>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
