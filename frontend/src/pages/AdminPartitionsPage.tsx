import { useState } from "react";
import { toast } from "sonner";
import {
  type PartitionArchiveOut,
  type PartitionArchiveStatus,
  useArchives,
  useRestoreArchive,
  useRunArchive,
} from "@/api/admin_partitions";
import { ApiError } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

const STATUSES: PartitionArchiveStatus[] = [
  "PENDING",
  "COPYING",
  "COPIED",
  "DETACHED",
  "DROPPED",
  "RESTORED",
  "FAILED",
];

const STATUS_VARIANT: Record<
  PartitionArchiveStatus,
  "default" | "muted" | "destructive" | "success"
> = {
  PENDING: "muted",
  COPYING: "default",
  COPIED: "default",
  DETACHED: "default",
  DROPPED: "success",
  RESTORED: "success",
  FAILED: "destructive",
};

export function AdminPartitionsPage() {
  const [statusFilter, setStatusFilter] = useState<PartitionArchiveStatus | "">("");
  const archives = useArchives({ status: statusFilter || null });

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex items-center gap-3 p-4 text-sm">
          <span className="text-muted-foreground">status:</span>
          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as PartitionArchiveStatus | "")
            }
            className="flex h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">(전체)</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <Thead>
              <Tr>
                <Th>ID</Th>
                <Th>partition</Th>
                <Th>row_count</Th>
                <Th>size</Th>
                <Th>status</Th>
                <Th>archived_at</Th>
                <Th>object</Th>
                <Th></Th>
              </Tr>
            </Thead>
            <Tbody>
              {archives.isLoading && (
                <Tr>
                  <Td colSpan={8} className="text-center text-muted-foreground">
                    로딩 중…
                  </Td>
                </Tr>
              )}
              {!archives.isLoading && (archives.data?.length ?? 0) === 0 && (
                <Tr>
                  <Td colSpan={8} className="text-center text-muted-foreground">
                    아카이브 후보가 없습니다.
                  </Td>
                </Tr>
              )}
              {archives.data?.map((a) => (
                <ArchiveRow key={a.archive_id} a={a} />
              ))}
            </Tbody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function _humanSize(bytes: number | null): string {
  if (bytes == null) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function ArchiveRow({ a }: { a: PartitionArchiveOut }) {
  const run = useRunArchive();
  const restore = useRestoreArchive();
  const [restoreTarget, setRestoreTarget] = useState("");
  const [showRestore, setShowRestore] = useState(false);

  return (
    <>
      <Tr>
        <Td className="font-mono text-xs">{a.archive_id}</Td>
        <Td className="font-mono text-xs">
          {a.schema_name}.{a.partition_name}
        </Td>
        <Td className="text-xs">{a.row_count ?? "-"}</Td>
        <Td className="text-xs">{_humanSize(a.byte_size)}</Td>
        <Td>
          <Badge variant={STATUS_VARIANT[a.status]}>{a.status}</Badge>
        </Td>
        <Td className="text-xs">
          {a.archived_at ? formatDateTime(a.archived_at) : "-"}
        </Td>
        <Td className="font-mono text-[11px] text-muted-foreground">
          {a.object_uri ?? "-"}
        </Td>
        <Td className="space-x-1 whitespace-nowrap">
          {(a.status === "PENDING" || a.status === "FAILED") && (
            <Button
              size="sm"
              variant="outline"
              disabled={run.isPending}
              onClick={() => {
                if (
                  !confirm(
                    `${a.schema_name}.${a.partition_name} 을 cold storage 로 복제 후 DROP 하시겠습니까? (되돌리려면 RESTORE 필요)`,
                  )
                )
                  return;
                run.mutate(a.archive_id, {
                  onSuccess: (res) => toast.success(res.detail),
                  onError: (err) =>
                    toast.error(err instanceof ApiError ? err.message : "실패"),
                });
              }}
            >
              {run.isPending ? "처리 중…" : "Archive"}
            </Button>
          )}
          {(a.status === "DROPPED" || a.status === "RESTORED") && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowRestore(true)}
            >
              Restore
            </Button>
          )}
        </Td>
      </Tr>
      {showRestore && (
        <Tr>
          <Td colSpan={8} className="bg-muted/30">
            <div className="flex items-center gap-2 p-2">
              <span className="text-xs text-muted-foreground">
                target_table (생략 시 <code>{a.partition_name}_restored</code>):
              </span>
              <Input
                value={restoreTarget}
                onChange={(e) => setRestoreTarget(e.target.value)}
                placeholder="schema.table"
                className="h-8 max-w-sm"
              />
              <Button
                size="sm"
                disabled={restore.isPending}
                onClick={() =>
                  restore.mutate(
                    {
                      archiveId: a.archive_id,
                      target_table: restoreTarget || null,
                    },
                    {
                      onSuccess: (res) => {
                        toast.success(res.detail);
                        setShowRestore(false);
                        setRestoreTarget("");
                      },
                      onError: (err) =>
                        toast.error(
                          err instanceof ApiError ? err.message : "실패",
                        ),
                    },
                  )
                }
              >
                복원
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowRestore(false)}
              >
                취소
              </Button>
            </div>
          </Td>
        </Tr>
      )}
    </>
  );
}
