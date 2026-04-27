// Phase 8.6 — Mock API 자체 검증 페이지.
//
// 외부 API 의존 없이 시스템 검증용. 운영자가 mock 응답을 등록하면 곧바로
// `/v2/mock-api/serve/{code}` URL 로 호출 가능하며, 같은 시스템의 Source/API Connector
// 가 이 URL 을 *외부 API 처럼* 사용 가능.
import { Copy, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  type MockEndpoint,
  type MockEndpointIn,
  type MockResponseFormat,
  useCreateMockEndpoint,
  useDeleteMockEndpoint,
  useMockEndpoints,
  useUpdateMockEndpoint,
} from "@/api/v2/mock_api";
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

const FORMATS: MockResponseFormat[] = ["json", "xml", "csv", "tsv", "text"];

const SAMPLE_BODY: Record<MockResponseFormat, string> = {
  json: `{
  "items": [
    {"id": 1, "name": "Sensor A", "value": 23.5},
    {"id": 2, "name": "Sensor B", "value": 31.2}
  ]
}`,
  xml: `<?xml version="1.0"?>
<response>
  <items>
    <item><id>1</id><name>Sensor A</name></item>
    <item><id>2</id><name>Sensor B</name></item>
  </items>
</response>`,
  csv: `id,name,value
1,Sensor A,23.5
2,Sensor B,31.2`,
  tsv: `id\tname\tvalue
1\tSensor A\t23.5
2\tSensor B\t31.2`,
  text: `2026-04-27 10:00 reading_a 23.5
2026-04-27 10:01 reading_b 31.2`,
};

export function MockApiPage() {
  const list = useMockEndpoints();
  const [editing, setEditing] = useState<MockEndpoint | null>(null);
  const [creating, setCreating] = useState(false);
  const remove = useDeleteMockEndpoint();

  const baseUrl = window.location.origin.replace(":5173", ":8000");

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Mock API (자체 검증 도구)</h2>
          <p className="text-sm text-muted-foreground">
            외부 API 의존 없이 시스템을 검증할 수 있도록, *우리 시스템 안에서 외부 API 흉내를 내는*
            endpoint 를 등록합니다. 등록한 endpoint 는 같은 시스템의 Source/API Connector 가 곧바로
            호출 가능합니다.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" />
          Mock 등록
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {list.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">불러오는 중…</div>
          )}
          {list.isError && (
            <div className="p-6 text-sm text-destructive">
              조회 실패: {(list.error as Error).message}
            </div>
          )}
          {list.data && list.data.length === 0 && (
            <div className="p-8 text-center text-sm text-muted-foreground">
              <p className="mb-2">등록된 Mock 이 없습니다.</p>
              <p className="text-xs">
                상단 [Mock 등록] 으로 시작하세요. JSON / XML / CSV / TSV / TEXT 5종 응답 포맷 지원.
              </p>
            </div>
          )}
          {list.data && list.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>code</Th>
                  <Th>name</Th>
                  <Th>format</Th>
                  <Th>serve URL</Th>
                  <Th>호출수</Th>
                  <Th>활성</Th>
                  <Th>동작</Th>
                </Tr>
              </Thead>
              <Tbody>
                {list.data.map((m) => {
                  const fullUrl = `${baseUrl}${m.serve_url_path}`;
                  return (
                    <Tr key={m.mock_id}>
                      <Td>
                        <code className="text-xs">{m.code}</code>
                      </Td>
                      <Td>{m.name}</Td>
                      <Td>
                        <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] font-mono">
                          {m.response_format}
                        </span>
                      </Td>
                      <Td>
                        <button
                          type="button"
                          onClick={() => {
                            navigator.clipboard.writeText(fullUrl);
                            toast.success("URL 복사됨");
                          }}
                          className="flex items-center gap-1 font-mono text-xs text-primary hover:underline"
                          title="클릭하여 복사"
                        >
                          <Copy className="h-3 w-3" />
                          {fullUrl}
                        </button>
                      </Td>
                      <Td className="text-xs">{m.call_count.toLocaleString()}</Td>
                      <Td>
                        <span
                          className={`text-xs ${m.is_active ? "text-emerald-600" : "text-muted-foreground"}`}
                        >
                          {m.is_active ? "ON" : "OFF"}
                        </span>
                      </Td>
                      <Td className="space-x-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditing(m)}
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            if (!confirm(`Mock '${m.code}' 삭제?`)) return;
                            await remove.mutateAsync(m.mock_id);
                            toast.success("삭제 완료");
                          }}
                        >
                          <Trash2 className="h-3 w-3 text-destructive" />
                        </Button>
                      </Td>
                    </Tr>
                  );
                })}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {creating && (
        <MockEditDialog mode="create" onClose={() => setCreating(false)} />
      )}
      {editing && (
        <MockEditDialog
          mode="edit"
          existing={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

interface MockEditDialogProps {
  mode: "create" | "edit";
  existing?: MockEndpoint;
  onClose: () => void;
}

function MockEditDialog({ mode, existing, onClose }: MockEditDialogProps) {
  const create = useCreateMockEndpoint();
  const update = useUpdateMockEndpoint();
  const [form, setForm] = useState<MockEndpointIn>(
    existing
      ? {
          code: existing.code,
          name: existing.name,
          description: existing.description,
          response_format: existing.response_format,
          response_body: existing.response_body,
          response_headers: existing.response_headers,
          status_code: existing.status_code,
          delay_ms: existing.delay_ms,
          is_active: existing.is_active,
        }
      : {
          code: "",
          name: "",
          description: "",
          response_format: "json",
          response_body: SAMPLE_BODY.json,
          response_headers: {},
          status_code: 200,
          delay_ms: 0,
          is_active: true,
        },
  );
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    setSubmitting(true);
    try {
      if (mode === "create") {
        await create.mutateAsync(form);
        toast.success("Mock 등록 완료");
      } else if (existing) {
        await update.mutateAsync({ mock_id: existing.mock_id, body: form });
        toast.success("Mock 수정 완료");
      }
      onClose();
    } catch (e) {
      toast.error(`저장 실패: ${(e as Error).message}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{mode === "create" ? "Mock 등록" : "Mock 수정"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium">code (URL slug)</label>
              <Input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
                placeholder="sample_iot_sensors"
                disabled={mode === "edit"}
              />
              <p className="mt-0.5 text-[10px] text-muted-foreground">
                a-z, 0-9, _ 만 — URL 의 일부가 됩니다 (/v2/mock-api/serve/{form.code || "..."})
              </p>
            </div>
            <div>
              <label className="text-xs font-medium">name</label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="센서 데이터 mock"
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium">설명 (선택)</label>
            <Input
              value={form.description ?? ""}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              placeholder="이 mock 의 용도를 한 줄로"
            />
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs font-medium">응답 포맷</label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
                value={form.response_format}
                onChange={(e) => {
                  const fmt = e.target.value as MockResponseFormat;
                  setForm({
                    ...form,
                    response_format: fmt,
                    response_body:
                      // 응답 body 가 비었거나 다른 포맷의 sample 이면 자동 교체
                      !form.response_body.trim() ||
                      Object.values(SAMPLE_BODY).includes(form.response_body)
                        ? SAMPLE_BODY[fmt]
                        : form.response_body,
                  });
                }}
              >
                {FORMATS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium">status code</label>
              <Input
                type="number"
                value={form.status_code}
                onChange={(e) =>
                  setForm({ ...form, status_code: Number(e.target.value) })
                }
                min={100}
                max={599}
              />
            </div>
            <div>
              <label className="text-xs font-medium">delay (ms)</label>
              <Input
                type="number"
                value={form.delay_ms}
                onChange={(e) =>
                  setForm({ ...form, delay_ms: Number(e.target.value) })
                }
                min={0}
                max={30000}
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium">응답 본문</label>
            <textarea
              className="mt-1 h-64 w-full rounded-md border bg-background p-2 font-mono text-xs"
              value={form.response_body}
              onChange={(e) =>
                setForm({ ...form, response_body: e.target.value })
              }
            />
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              ※ 외부 API 가 반환할 응답을 그대로 입력. 포맷 변경 시 sample 자동 교체.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            />
            <span>활성 (체크 해제 시 serve endpoint 가 404 반환)</span>
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            취소
          </Button>
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? "저장 중…" : "저장"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
