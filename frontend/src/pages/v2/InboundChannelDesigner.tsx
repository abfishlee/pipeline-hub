import {
  Clipboard,
  Copy,
  FileInput,
  Globe,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  TimerReset,
  Webhook,
  Workflow,
} from "lucide-react";
import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { type WorkflowOut, useWorkflows } from "@/api/pipelines";
import { useDomains } from "@/api/v2/domains";
import {
  type AuthMethod,
  type ChannelKind,
  type ChannelStatus,
  type InboundChannel,
  type InboundChannelIn,
  useCreateInboundChannel,
  useDeleteInboundChannel,
  useInboundChannels,
  useTransitionInboundChannel,
  useUpdateInboundChannel,
} from "@/api/v2/inbound_channels";
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

const KINDS: ChannelKind[] = [
  "WEBHOOK",
  "FILE_UPLOAD",
  "OCR_RESULT",
  "CRAWLER_RESULT",
];

const KIND_META: Record<
  ChannelKind,
  {
    label: string;
    description: string;
    contentType: string;
    icon: React.ComponentType<{ className?: string }>;
  }
> = {
  WEBHOOK: {
    label: "Webhook / 외부 Push",
    description: "유통사, 협력사, 외부 시스템이 JSON 이벤트를 실시간으로 보냅니다.",
    contentType: "application/json",
    icon: Webhook,
  },
  FILE_UPLOAD: {
    label: "File Upload",
    description: "사용자나 외부 시스템이 CSV, Excel, JSON 파일을 업로드합니다.",
    contentType: "text/csv",
    icon: FileInput,
  },
  OCR_RESULT: {
    label: "OCR Result",
    description: "OCR 업체가 가격표/영수증 인식 결과를 push합니다.",
    contentType: "application/json",
    icon: Clipboard,
  },
  CRAWLER_RESULT: {
    label: "Crawler Result",
    description: "크롤러가 온라인몰/웹 가격 수집 결과를 push합니다.",
    contentType: "application/json",
    icon: Globe,
  },
};

const STATUS_OPTIONS: ChannelStatus[] = [
  "DRAFT",
  "REVIEW",
  "APPROVED",
  "PUBLISHED",
];

function statusVariant(
  s: ChannelStatus,
): "default" | "secondary" | "success" | "warning" | "muted" {
  switch (s) {
    case "DRAFT":
      return "muted";
    case "REVIEW":
      return "warning";
    case "APPROVED":
      return "default";
    case "PUBLISHED":
      return "success";
  }
}

function formatBytes(bytes: number) {
  if (bytes >= 1024 * 1024) return `${Math.round(bytes / 1024 / 1024)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

function workflowLabel(workflows: WorkflowOut[] | undefined, workflowId: number | null) {
  if (!workflowId) return "수동 처리";
  const wf = workflows?.find((w) => w.workflow_id === workflowId);
  return wf ? `#${wf.workflow_id} ${wf.name}` : `#${workflowId}`;
}

export function InboundChannelDesigner() {
  const domains = useDomains();
  const workflows = useWorkflows({ status: "PUBLISHED", limit: 200 });
  const [domainCode, setDomainCode] = useState("");
  const [kindFilter, setKindFilter] = useState<ChannelKind | "">("");
  const [statusFilter, setStatusFilter] = useState<ChannelStatus | "">("");
  const channels = useInboundChannels({
    domain_code: domainCode || undefined,
    channel_kind: kindFilter || undefined,
    status: statusFilter || undefined,
  });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<InboundChannel | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Inbound Channel</h2>
          <p className="max-w-4xl text-sm text-muted-foreground">
            외부에서 우리 시스템으로 들어오는 Push, 파일, OCR, 크롤링 결과의 수신 입구입니다.
            데이터가 수신되면 envelope로 보관되고, 연결된 Job이 이벤트 기반으로 실행됩니다.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/v2/inbound-events">
            <Button variant="outline">
              <Clipboard className="h-4 w-4" />
              Inbound Inbox
            </Button>
          </Link>
          <Button onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            새 채널
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        {KINDS.map((kind) => {
          const Icon = KIND_META[kind].icon;
          return (
            <Card key={kind}>
              <CardContent className="flex gap-3 p-4">
                <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                  <Icon className="h-4 w-4" />
                </div>
                <div className="space-y-1">
                  <div className="text-sm font-medium">{KIND_META[kind].label}</div>
                  <p className="text-xs leading-5 text-muted-foreground">
                    {KIND_META[kind].description}
                  </p>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div>
            <label className="text-xs text-muted-foreground">도메인</label>
            <select
              className="mt-1 h-9 w-52 rounded-md border bg-background px-3 text-sm"
              value={domainCode}
              onChange={(e) => setDomainCode(e.target.value)}
            >
              <option value="">전체</option>
              {domains.data?.map((d) => (
                <option key={d.domain_code} value={d.domain_code}>
                  {d.domain_code} ({d.name})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">수신 방식</label>
            <select
              className="mt-1 h-9 w-48 rounded-md border bg-background px-3 text-sm"
              value={kindFilter}
              onChange={(e) =>
                setKindFilter((e.target.value || "") as ChannelKind | "")
              }
            >
              <option value="">전체</option>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {KIND_META[k].label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">상태</label>
            <select
              className="mt-1 h-9 w-36 rounded-md border bg-background px-3 text-sm"
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter((e.target.value || "") as ChannelStatus | "")
              }
            >
              <option value="">전체</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {channels.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">불러오는 중...</div>
          )}
          {channels.error && (
            <div className="p-6 text-sm text-destructive">
              조회 실패: {(channels.error as Error).message}
            </div>
          )}
          {channels.data && channels.data.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              등록된 inbound channel이 없습니다. 새 채널을 만들고 연결할 Job을 지정해 주세요.
            </div>
          )}
          {channels.data && channels.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>채널</Th>
                  <Th>도메인</Th>
                  <Th>수신 방식</Th>
                  <Th>트리거</Th>
                  <Th>보안/제한</Th>
                  <Th>상태</Th>
                  <Th>수정</Th>
                </Tr>
              </Thead>
              <Tbody>
                {channels.data.map((c) => (
                  <Tr key={c.channel_id}>
                    <Td>
                      <div className="font-medium">{c.name}</div>
                      <code className="text-xs text-muted-foreground">
                        {c.channel_code}
                      </code>
                    </Td>
                    <Td className="text-xs">{c.domain_code}</Td>
                    <Td>
                      <Badge variant="secondary">{KIND_META[c.channel_kind].label}</Badge>
                    </Td>
                    <Td className="text-xs">
                      <div className="font-medium">
                        {c.workflow_id ? "Event Trigger" : "Manual"}
                      </div>
                      <div className="text-muted-foreground">
                        {workflowLabel(workflows.data, c.workflow_id)}
                      </div>
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {c.auth_method} · {formatBytes(c.max_payload_bytes)} ·{" "}
                      {c.rate_limit_per_min}/min
                    </Td>
                    <Td>
                      <div className="flex items-center gap-2">
                        <Badge variant={statusVariant(c.status)}>{c.status}</Badge>
                        <Badge variant={c.is_active ? "success" : "muted"}>
                          {c.is_active ? "active" : "off"}
                        </Badge>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {formatDateTime(c.updated_at)}
                      </div>
                    </Td>
                    <Td>
                      <Button variant="ghost" size="sm" onClick={() => setEditing(c)}>
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {creating && (
        <ChannelEditDialog
          mode="create"
          open={creating}
          workflows={workflows.data ?? []}
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <ChannelEditDialog
          mode="edit"
          open={!!editing}
          existing={editing}
          workflows={workflows.data ?? []}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

interface ChannelEditDialogProps {
  mode: "create" | "edit";
  open: boolean;
  existing?: InboundChannel;
  workflows: WorkflowOut[];
  onClose: () => void;
}

function ChannelEditDialog({
  mode,
  open,
  existing,
  workflows,
  onClose,
}: ChannelEditDialogProps) {
  const domains = useDomains();
  const create = useCreateInboundChannel();
  const update = useUpdateInboundChannel(existing?.channel_id ?? 0);
  const transition = useTransitionInboundChannel(existing?.channel_id ?? 0);
  const remove = useDeleteInboundChannel();

  const [form, setForm] = useState<InboundChannelIn>({
    channel_code: "",
    domain_code: "",
    name: "",
    description: "",
    channel_kind: "WEBHOOK",
    secret_ref: "",
    auth_method: "hmac_sha256",
    expected_content_type: "application/json",
    max_payload_bytes: 10_485_760,
    rate_limit_per_min: 100,
    replay_window_sec: 300,
    workflow_id: null,
  });

  useEffect(() => {
    if (mode === "edit" && existing) {
      setForm({
        channel_code: existing.channel_code,
        domain_code: existing.domain_code,
        name: existing.name,
        description: existing.description ?? "",
        channel_kind: existing.channel_kind,
        secret_ref: existing.secret_ref,
        auth_method: existing.auth_method,
        expected_content_type: existing.expected_content_type ?? "",
        max_payload_bytes: existing.max_payload_bytes,
        rate_limit_per_min: existing.rate_limit_per_min,
        replay_window_sec: existing.replay_window_sec,
        workflow_id: existing.workflow_id,
      });
      return;
    }
    setForm({
      channel_code: "",
      domain_code: domains.data?.[0]?.domain_code ?? "",
      name: "",
      description: "",
      channel_kind: "WEBHOOK",
      secret_ref: "",
      auth_method: "hmac_sha256",
      expected_content_type: "application/json",
      max_payload_bytes: 10_485_760,
      rate_limit_per_min: 100,
      replay_window_sec: 300,
      workflow_id: null,
    });
  }, [mode, existing, domains.data]);

  const isReadOnly = mode === "edit" && existing && existing.status !== "DRAFT";
  const selectedKind = KIND_META[form.channel_kind];
  const endpointPath = `/v1/inbound/${form.channel_code || "{channel_code}"}`;
  const endpointUrl = `${window.location.origin}${endpointPath}`;

  function updateKind(kind: ChannelKind) {
    setForm({
      ...form,
      channel_kind: kind,
      expected_content_type: KIND_META[kind].contentType,
    });
  }

  async function handleSubmit() {
    try {
      if (mode === "create") {
        await create.mutateAsync({
          ...form,
          description: form.description?.trim() || null,
          expected_content_type: form.expected_content_type?.trim() || null,
          workflow_id: form.workflow_id || null,
        });
        toast.success("Inbound Channel을 DRAFT로 등록했습니다");
        onClose();
      } else if (existing) {
        await update.mutateAsync({
          name: form.name,
          description: form.description?.trim() || null,
          secret_ref: form.secret_ref,
          expected_content_type: form.expected_content_type?.trim() || null,
          max_payload_bytes: form.max_payload_bytes,
          rate_limit_per_min: form.rate_limit_per_min,
          replay_window_sec: form.replay_window_sec,
          workflow_id: form.workflow_id || null,
        });
        toast.success("저장했습니다");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`저장 실패: ${msg}`);
    }
  }

  async function handleTransition(target: ChannelStatus) {
    if (!existing) return;
    try {
      await transition.mutateAsync(target);
      toast.success(`상태를 ${target}로 변경했습니다`);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`상태 변경 실패: ${msg}`);
    }
  }

  async function handleDelete() {
    if (!existing) return;
    if (!confirm(`channel ${existing.channel_code}을 삭제할까요?`)) return;
    try {
      await remove.mutateAsync(existing.channel_id);
      toast.success("삭제했습니다");
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`삭제 실패: ${msg}`);
    }
  }

  function copyEndpoint() {
    navigator.clipboard.writeText(endpointUrl);
    toast.success("Endpoint를 복사했습니다");
  }

  const transitionsFromCurrent: ChannelStatus[] = useMemo(() => {
    if (!existing) return [];
    switch (existing.status) {
      case "DRAFT":
        return ["REVIEW"];
      case "REVIEW":
        return ["APPROVED", "DRAFT"];
      case "APPROVED":
        return ["PUBLISHED", "DRAFT"];
      case "PUBLISHED":
        return ["DRAFT"];
    }
  }, [existing]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? "새 Inbound Channel" : `채널 수정: ${existing?.channel_code}`}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-4">
            <section className="space-y-3 rounded-md border p-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Webhook className="h-4 w-4 text-primary" />
                1. 수신 채널
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <Field label="channel_code">
                  <Input
                    value={form.channel_code}
                    onChange={(e) =>
                      setForm({ ...form, channel_code: e.target.value })
                    }
                    disabled={mode === "edit"}
                    placeholder="vendor_a_price_push"
                  />
                </Field>
                <Field label="도메인">
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                    value={form.domain_code}
                    onChange={(e) =>
                      setForm({ ...form, domain_code: e.target.value })
                    }
                    disabled={mode === "edit"}
                  >
                    <option value="">선택</option>
                    {domains.data?.map((d) => (
                      <option key={d.domain_code} value={d.domain_code}>
                        {d.domain_code} ({d.name})
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="수신 방식">
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                    value={form.channel_kind}
                    onChange={(e) => updateKind(e.target.value as ChannelKind)}
                    disabled={mode === "edit"}
                  >
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {KIND_META[k].label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
                {selectedKind.description}
              </div>
              <Field label="이름">
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="A 유통사 가격 webhook"
                />
              </Field>
              <Field label="설명">
                <Input
                  value={form.description ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, description: e.target.value })
                  }
                  disabled={!!isReadOnly}
                  placeholder="원천, 데이터 형태, 운영 담당자 메모"
                />
              </Field>
            </section>

            <section className="space-y-3 rounded-md border p-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Workflow className="h-4 w-4 text-primary" />
                2. 수신 후 실행
              </div>
              <div className="grid gap-3 md:grid-cols-[1fr_180px]">
                <Field label="연결 Job / Workflow">
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                    value={form.workflow_id ?? ""}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        workflow_id: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                    disabled={!!isReadOnly}
                  >
                    <option value="">연결 안 함: Inbox에만 쌓고 수동 처리</option>
                    {workflows.map((w) => (
                      <option key={w.workflow_id} value={w.workflow_id}>
                        #{w.workflow_id} {w.name} v{w.version}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Trigger Type">
                  <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/40 px-3 text-sm">
                    {form.workflow_id ? "Event Trigger" : "Manual"}
                  </div>
                </Field>
              </div>
              <div className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
                Push 수집은 우리가 주기를 정하지 않습니다. 데이터가 들어오면 연결된 Job이 실행되고,
                연결하지 않으면 Inbound Inbox에서 검수 후 수동 처리합니다.
              </div>
            </section>

            <section className="space-y-3 rounded-md border p-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <ShieldCheck className="h-4 w-4 text-primary" />
                3. 보안과 수신 제한
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="auth_method">
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                    value={form.auth_method}
                    onChange={(e) =>
                      setForm({ ...form, auth_method: e.target.value as AuthMethod })
                    }
                    disabled={mode === "edit"}
                  >
                    <option value="hmac_sha256">hmac_sha256</option>
                    <option value="api_key">api_key</option>
                    <option value="mtls" disabled>
                      mtls
                    </option>
                  </select>
                </Field>
                <Field label="secret_ref (env name)">
                  <Input
                    value={form.secret_ref}
                    onChange={(e) =>
                      setForm({ ...form, secret_ref: e.target.value })
                    }
                    disabled={!!isReadOnly}
                    placeholder="VENDOR_A_HMAC_SECRET"
                  />
                </Field>
              </div>
              <div className="grid gap-3 md:grid-cols-4">
                <Field label="content_type">
                  <Input
                    value={form.expected_content_type ?? ""}
                    onChange={(e) =>
                      setForm({ ...form, expected_content_type: e.target.value })
                    }
                    disabled={!!isReadOnly}
                  />
                </Field>
                <Field label="max payload">
                  <Input
                    type="number"
                    value={form.max_payload_bytes ?? 10_485_760}
                    onChange={(e) =>
                      setForm({ ...form, max_payload_bytes: Number(e.target.value) })
                    }
                    disabled={!!isReadOnly}
                  />
                </Field>
                <Field label="rate limit/min">
                  <Input
                    type="number"
                    value={form.rate_limit_per_min ?? 100}
                    onChange={(e) =>
                      setForm({ ...form, rate_limit_per_min: Number(e.target.value) })
                    }
                    disabled={!!isReadOnly}
                  />
                </Field>
                <Field label="replay window/sec">
                  <Input
                    type="number"
                    min={30}
                    max={3600}
                    value={form.replay_window_sec ?? 300}
                    onChange={(e) =>
                      setForm({ ...form, replay_window_sec: Number(e.target.value) })
                    }
                    disabled={!!isReadOnly}
                  />
                </Field>
              </div>
            </section>
          </div>

          <aside className="space-y-4">
            <section className="space-y-3 rounded-md border p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <Globe className="h-4 w-4 text-primary" />
                  외부 공유 Endpoint
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={copyEndpoint}
                  disabled={!form.channel_code}
                >
                  <Copy className="h-3 w-3" />
                  복사
                </Button>
              </div>
              <code className="block break-all rounded bg-muted/50 p-3 text-xs">
                POST {endpointUrl}
              </code>
              <div className="space-y-2 text-xs text-muted-foreground">
                <div className="font-medium text-foreground">필수 헤더</div>
                <code className="block rounded bg-muted/40 p-2">
                  X-Idempotency-Key: unique-event-id
                </code>
                {form.auth_method === "hmac_sha256" ? (
                  <>
                    <code className="block rounded bg-muted/40 p-2">
                      X-Timestamp: unix epoch seconds
                    </code>
                    <code className="block rounded bg-muted/40 p-2">
                      X-Signature: hmac-sha256=&lt;hex&gt;
                    </code>
                  </>
                ) : (
                  <code className="block rounded bg-muted/40 p-2">
                    X-API-Key: issued-secret
                  </code>
                )}
              </div>
            </section>

            <section className="space-y-3 rounded-md border p-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <TimerReset className="h-4 w-4 text-primary" />
                처리 흐름
              </div>
              <ol className="space-y-2 text-xs text-muted-foreground">
                <li>1. 외부 시스템이 endpoint로 데이터를 push합니다.</li>
                <li>2. payload는 audit.inbound_event에 envelope로 저장됩니다.</li>
                <li>3. 연결 Job이 있으면 Event Trigger로 run이 생성됩니다.</li>
                <li>4. Job이 정규화, 표준화, DQ, 마트 적재를 수행합니다.</li>
              </ol>
            </section>

            {isReadOnly && existing && (
              <section className="rounded-md border bg-muted/40 p-4 text-xs text-muted-foreground">
                현재 상태는 {existing.status}입니다. DRAFT 상태에서만 직접 수정할 수 있고,
                PUBLISHED 상태의 채널만 실제 inbound 수신을 받습니다.
              </section>
            )}
          </aside>
        </div>

        <DialogFooter className="flex-wrap gap-2">
          {mode === "edit" && existing && (
            <>
              {transitionsFromCurrent.map((t) => (
                <Button key={t} variant="secondary" size="sm" onClick={() => handleTransition(t)}>
                  <Send className="h-3 w-3" />
                  {t}로 변경
                </Button>
              ))}
              {existing.status !== "PUBLISHED" && (
                <Button variant="destructive" size="sm" onClick={handleDelete}>
                  삭제
                </Button>
              )}
            </>
          )}
          <Button variant="outline" onClick={onClose}>
            닫기
          </Button>
          {!isReadOnly && (
            <Button onClick={handleSubmit}>
              <RefreshCw className="h-4 w-4" />
              {mode === "create" ? "등록" : "저장"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
