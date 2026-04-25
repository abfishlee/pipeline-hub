import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  type DataSource,
  type DataSourceCreate,
  type DataSourceUpdate,
  type SourceType,
  useCreateSource,
  useDeleteSource,
  useSources,
  useUpdateSource,
} from "@/api/sources";
import { ApiError } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";
import { useAuthStore } from "@/store/auth";

const SOURCE_TYPES: SourceType[] = [
  "API",
  "OCR",
  "DB",
  "CRAWLER",
  "CROWD",
  "RECEIPT",
  "APP",
];

export function SourcesPage() {
  const isAdmin = useAuthStore((s) => s.user?.roles.includes("ADMIN") ?? false);
  const sources = useSources({ limit: 100 });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<DataSource | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          수집 데이터 소스 정의. 변경/삭제는 ADMIN 만 가능.
        </p>
        {isAdmin && (
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            새 소스
          </Button>
        )}
      </div>

      <Card>
        <CardContent className="p-0">
          {sources.isLoading && <div className="p-4 text-sm">불러오는 중...</div>}
          {sources.error && (
            <div className="p-4 text-sm text-destructive">
              {(sources.error as Error).message}
            </div>
          )}
          {sources.data && (
            <Table>
              <Thead>
                <Tr>
                  <Th>ID</Th>
                  <Th>소스코드</Th>
                  <Th>이름</Th>
                  <Th>타입</Th>
                  <Th>활성</Th>
                  <Th>스케줄</Th>
                  <Th>생성일</Th>
                  {isAdmin && <Th className="w-32"></Th>}
                </Tr>
              </Thead>
              <Tbody>
                {sources.data.map((s) => (
                  <Tr key={s.source_id}>
                    <Td className="font-mono text-xs">{s.source_id}</Td>
                    <Td className="font-mono">{s.source_code}</Td>
                    <Td>{s.source_name}</Td>
                    <Td>
                      <Badge variant="secondary">{s.source_type}</Badge>
                    </Td>
                    <Td>
                      {s.is_active ? (
                        <Badge variant="success">활성</Badge>
                      ) : (
                        <Badge variant="muted">비활성</Badge>
                      )}
                    </Td>
                    <Td className="font-mono text-xs">{s.schedule_cron ?? "-"}</Td>
                    <Td className="text-xs">{formatDateTime(s.created_at)}</Td>
                    {isAdmin && (
                      <Td className="text-right">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setEditing(s)}
                          title="수정"
                        >
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <DeleteButton sourceId={s.source_id} />
                      </Td>
                    )}
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <CreateDialog open={creating} onOpenChange={setCreating} />
      <EditDialog source={editing} onOpenChange={(o) => !o && setEditing(null)} />
    </div>
  );
}

function DeleteButton({ sourceId }: { sourceId: number }) {
  const del = useDeleteSource();
  return (
    <Button
      variant="ghost"
      size="icon"
      title="비활성화"
      disabled={del.isPending}
      onClick={() => {
        if (!confirm("이 소스를 비활성화하시겠습니까? (soft delete)")) return;
        del.mutate(sourceId, {
          onSuccess: () => toast.success("비활성화됨"),
          onError: (err) =>
            toast.error(err instanceof ApiError ? err.message : "삭제 실패"),
        });
      }}
    >
      <Trash2 className="h-4 w-4 text-destructive" />
    </Button>
  );
}

function CreateDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [form, setForm] = useState<DataSourceCreate>({
    source_code: "",
    source_name: "",
    source_type: "API",
  });
  const create = useCreateSource();

  function reset() {
    setForm({ source_code: "", source_name: "", source_type: "API" });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>새 데이터 소스</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <FormRow label="source_code (대문자 + 언더스코어, 3~64자)">
            <Input
              value={form.source_code}
              onChange={(e) =>
                setForm((f) => ({ ...f, source_code: e.target.value }))
              }
              placeholder="예: EMART_OPEN_API"
            />
          </FormRow>
          <FormRow label="source_name">
            <Input
              value={form.source_name}
              onChange={(e) =>
                setForm((f) => ({ ...f, source_name: e.target.value }))
              }
            />
          </FormRow>
          <FormRow label="source_type">
            <select
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
              value={form.source_type}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  source_type: e.target.value as SourceType,
                }))
              }
            >
              {SOURCE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </FormRow>
          <FormRow label="schedule_cron (선택)">
            <Input
              placeholder="예: */10 * * * *"
              value={form.schedule_cron ?? ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, schedule_cron: e.target.value || null }))
              }
            />
          </FormRow>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            취소
          </Button>
          <Button
            disabled={create.isPending}
            onClick={() => {
              create.mutate(form, {
                onSuccess: () => {
                  toast.success("소스 생성 완료");
                  reset();
                  onOpenChange(false);
                },
                onError: (err) =>
                  toast.error(
                    err instanceof ApiError ? err.message : "생성 실패",
                  ),
              });
            }}
          >
            생성
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditDialog({
  source,
  onOpenChange,
}: {
  source: DataSource | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [form, setForm] = useState<DataSourceUpdate>({});
  const update = useUpdateSource(source?.source_id ?? 0);

  return (
    <Dialog open={source != null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>소스 수정 — {source?.source_code}</DialogTitle>
        </DialogHeader>
        {source && (
          <div className="space-y-4">
            <FormRow label="source_name">
              <Input
                defaultValue={source.source_name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, source_name: e.target.value }))
                }
              />
            </FormRow>
            <FormRow label="schedule_cron">
              <Input
                defaultValue={source.schedule_cron ?? ""}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    schedule_cron: e.target.value || null,
                  }))
                }
              />
            </FormRow>
            <FormRow label="활성 여부">
              <select
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                defaultValue={source.is_active ? "true" : "false"}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    is_active: e.target.value === "true",
                  }))
                }
              >
                <option value="true">활성</option>
                <option value="false">비활성</option>
              </select>
            </FormRow>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            취소
          </Button>
          <Button
            disabled={update.isPending}
            onClick={() => {
              update.mutate(form, {
                onSuccess: () => {
                  toast.success("수정 완료");
                  onOpenChange(false);
                },
                onError: (err) =>
                  toast.error(
                    err instanceof ApiError ? err.message : "수정 실패",
                  ),
              });
            }}
          >
            저장
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FormRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
    </div>
  );
}
