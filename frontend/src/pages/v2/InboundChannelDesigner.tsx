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
  useInboundChannelContract,
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
    label: "Webhook Push",
    description: "External systems push product or price events as JSON.",
    contentType: "application/json",
    icon: Webhook,
  },
  FILE_UPLOAD: {
    label: "File Upload",
    description: "Users or partners upload CSV, Excel, or JSON files.",
    contentType: "text/csv",
    icon: FileInput,
  },
  OCR_RESULT: {
    label: "OCR Result",
    description: "OCR vendors push recognized price-table or receipt results.",
    contentType: "application/json",
    icon: Clipboard,
  },
  CRAWLER_RESULT: {
    label: "Crawler Result",
    description: "Crawlers push web price collection results.",
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
  if (!workflowId) return "Manual handling";
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
            Register push entry points for webhook, OCR, crawler, and file data.
            Each channel owns authentication, payload contract, size limits, and
            the event-triggered Job that runs after data arrives.
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
            New Channel
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
          <Field label="Domain">
            <select
              className="mt-1 h-9 w-52 rounded-md border bg-background px-3 text-sm"
              value={domainCode}
              onChange={(e) => setDomainCode(e.target.value)}
            >
              <option value="">All</option>
              {domains.data?.map((d) => (
                <option key={d.domain_code} value={d.domain_code}>
                  {d.domain_code} ({d.name})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Kind">
            <select
              className="mt-1 h-9 w-48 rounded-md border bg-background px-3 text-sm"
              value={kindFilter}
              onChange={(e) =>
                setKindFilter((e.target.value || "") as ChannelKind | "")
              }
            >
              <option value="">All</option>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {KIND_META[k].label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Status">
            <select
              className="mt-1 h-9 w-36 rounded-md border bg-background px-3 text-sm"
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter((e.target.value || "") as ChannelStatus | "")
              }
            >
              <option value="">All</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {channels.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">Loading...</div>
          )}
          {channels.error && (
            <div className="p-6 text-sm text-destructive">
              Load failed: {(channels.error as Error).message}
            </div>
          )}
          {channels.data && channels.data.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              No inbound channels yet. Create a channel, publish it, then share
              its endpoint and API spec with the sender.
            </div>
          )}
          {channels.data && channels.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>Channel</Th>
                  <Th>Domain</Th>
                  <Th>Kind</Th>
                  <Th>Trigger</Th>
                  <Th>Security / Limits</Th>
                  <Th>Status</Th>
                  <Th></Th>
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
                      <Badge variant="secondary">
                        {KIND_META[c.channel_kind].label}
                      </Badge>
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
  const contract = useInboundChannelContract(existing?.channel_id ?? null);
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
  const samplePayload =
    contract.data?.sample_payload ?? defaultSamplePayload(form.channel_kind);
  const payloadSchema =
    contract.data?.payload_schema ?? defaultPayloadSchema(form.channel_kind);

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
        toast.success("Inbound channel created as DRAFT");
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
        toast.success("Saved");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`Save failed: ${msg}`);
    }
  }

  async function handleTransition(target: ChannelStatus) {
    if (!existing) return;
    try {
      await transition.mutateAsync(target);
      toast.success(`Status changed to ${target}`);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`Transition failed: ${msg}`);
    }
  }

  async function handleDelete() {
    if (!existing) return;
    if (!confirm(`Delete channel ${existing.channel_code}?`)) return;
    try {
      await remove.mutateAsync(existing.channel_id);
      toast.success("Deleted");
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`Delete failed: ${msg}`);
    }
  }

  function copyText(label: string, text: string) {
    navigator.clipboard.writeText(text);
    toast.success(`${label} copied`);
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
      <DialogContent className="max-w-6xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? "New Inbound Channel" : `Channel: ${existing?.channel_code}`}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="space-y-4">
            <section className="space-y-3 rounded-md border p-4">
              <SectionTitle icon={Webhook} title="1. Entry point" />
              <div className="grid gap-3 md:grid-cols-3">
                <Field label="channel_code">
                  <Input
                    value={form.channel_code}
                    onChange={(e) =>
                      setForm({ ...form, channel_code: e.target.value })
                    }
                    disabled={mode === "edit"}
                    placeholder="vendor_a_price_webhook"
                  />
                </Field>
                <Field label="domain">
                  <select
                    className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                    value={form.domain_code}
                    onChange={(e) =>
                      setForm({ ...form, domain_code: e.target.value })
                    }
                    disabled={mode === "edit"}
                  >
                    <option value="">Select</option>
                    {domains.data?.map((d) => (
                      <option key={d.domain_code} value={d.domain_code}>
                        {d.domain_code} ({d.name})
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="kind">
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
              <Field label="name">
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Vendor A price webhook"
                />
              </Field>
              <Field label="description">
                <Input
                  value={form.description ?? ""}
                  onChange={(e) =>
                    setForm({ ...form, description: e.target.value })
                  }
                  disabled={!!isReadOnly}
                  placeholder="Source owner, payload notes, operating memo"
                />
              </Field>
            </section>

            <section className="space-y-3 rounded-md border p-4">
              <SectionTitle icon={Workflow} title="2. Event trigger" />
              <div className="grid gap-3 md:grid-cols-[1fr_180px]">
                <Field label="Job / Workflow to run after receive">
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
                    <option value="">No job: keep in Inbox for manual handling</option>
                    {workflows.map((w) => (
                      <option key={w.workflow_id} value={w.workflow_id}>
                        #{w.workflow_id} {w.name} v{w.version}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="trigger type">
                  <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/40 px-3 text-sm">
                    {form.workflow_id ? "Event Trigger" : "Manual"}
                  </div>
                </Field>
              </div>
              <p className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
                Push collection has no cron schedule. The sender controls when
                data arrives; this channel controls what Job runs after receive.
              </p>
            </section>

            <section className="space-y-3 rounded-md border p-4">
              <SectionTitle icon={ShieldCheck} title="3. Security and limits" />
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
                <Field label="secret_ref (environment variable)">
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
                <Field label="max payload bytes">
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
                <SectionTitle icon={Globe} title="API spec for sender" />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => copyText("Endpoint", endpointUrl)}
                  disabled={!form.channel_code}
                >
                  <Copy className="h-3 w-3" />
                  Copy URL
                </Button>
              </div>
              <code className="block break-all rounded bg-muted/50 p-3 text-xs">
                POST {endpointUrl}
              </code>
              <div className="space-y-2 text-xs text-muted-foreground">
                <div className="font-medium text-foreground">Required headers</div>
                <code className="block rounded bg-muted/40 p-2">
                  Content-Type: {form.expected_content_type || "application/json"}
                </code>
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
              <div className="flex items-center justify-between">
                <SectionTitle icon={Clipboard} title="Payload contract" />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    copyText("Sample payload", JSON.stringify(samplePayload, null, 2))
                  }
                >
                  <Copy className="h-3 w-3" />
                  Copy sample
                </Button>
              </div>
              <div className="grid gap-2 text-xs">
                <div>
                  <div className="mb-1 font-medium">Item path</div>
                  <code className="block rounded bg-muted/40 p-2">
                    {contract.data?.item_path ?? "items"}
                  </code>
                </div>
                <div>
                  <div className="mb-1 font-medium">Sample payload</div>
                  <pre className="max-h-56 overflow-auto rounded bg-muted/40 p-3 text-[11px]">
                    {JSON.stringify(samplePayload, null, 2)}
                  </pre>
                </div>
                <details>
                  <summary className="cursor-pointer text-muted-foreground">
                    JSON schema
                  </summary>
                  <pre className="mt-2 max-h-56 overflow-auto rounded bg-muted/40 p-3 text-[11px]">
                    {JSON.stringify(payloadSchema, null, 2)}
                  </pre>
                </details>
              </div>
            </section>

            <section className="space-y-3 rounded-md border p-4">
              <SectionTitle icon={TimerReset} title="Processing flow" />
              <ol className="space-y-2 text-xs text-muted-foreground">
                <li>1. Sender posts data to the endpoint.</li>
                <li>2. HMAC/API key, replay window, idempotency, and schema are checked.</li>
                <li>3. Accepted payload is stored as audit.inbound_event.</li>
                <li>4. Connected workflow is triggered, or the envelope waits in Inbox.</li>
              </ol>
            </section>

            {isReadOnly && existing && (
              <section className="rounded-md border bg-muted/40 p-4 text-xs text-muted-foreground">
                Status is {existing.status}. Only DRAFT channels are directly editable.
                Only PUBLISHED active channels accept inbound data.
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
                  Move to {t}
                </Button>
              ))}
              {existing.status !== "PUBLISHED" && (
                <Button variant="destructive" size="sm" onClick={handleDelete}>
                  Delete
                </Button>
              )}
            </>
          )}
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          {!isReadOnly && (
            <Button onClick={handleSubmit}>
              <RefreshCw className="h-4 w-4" />
              {mode === "create" ? "Register" : "Save"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SectionTitle({
  icon: Icon,
  title,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
}) {
  return (
    <div className="flex items-center gap-2 text-sm font-semibold">
      <Icon className="h-4 w-4 text-primary" />
      {title}
    </div>
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

function defaultSamplePayload(kind: ChannelKind) {
  if (kind === "OCR_RESULT") {
    return {
      event_id: "ocr-20260428-0001",
      vendor_code: "local_ocr",
      document_id: "receipt-001",
      captured_at: "2026-04-28T12:00:00+09:00",
      items: [
        {
          product_name: "apple 10kg",
          price: 32000,
          unit: "box",
          store_name: "A Mart Gangnam",
          confidence: 0.93,
        },
      ],
    };
  }
  return {
    event_id: "vendor-a-20260428-0001",
    vendor_code: "vendor_a",
    captured_at: "2026-04-28T12:00:00+09:00",
    items: [
      {
        product_name: "apple 10kg",
        price: 32000,
        unit: "box",
        store_name: "A Mart Gangnam",
      },
    ],
  };
}

function defaultPayloadSchema(kind: ChannelKind) {
  const itemRequired =
    kind === "OCR_RESULT"
      ? ["product_name", "price", "confidence"]
      : ["product_name", "price"];
  return {
    type: "object",
    required: ["event_id", "vendor_code", "captured_at", "items"],
    properties: {
      event_id: { type: "string" },
      vendor_code: { type: "string" },
      captured_at: { type: "string" },
      items: {
        type: "array",
        items: {
          type: "object",
          required: itemRequired,
          properties: {
            product_name: { type: "string" },
            price: { type: "number" },
            unit: { type: "string" },
            store_name: { type: "string" },
            confidence: { type: "number" },
          },
        },
      },
    },
  };
}
