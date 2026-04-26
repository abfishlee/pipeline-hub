// Phase 7 Wave 1A — Inbound Channel Designer (외부 push 채널 등록).
//
// 사용자 시나리오:
//   1. 외부 업체 (크롤러 / OCR / 소상공인 업로드) 가 우리에게 데이터 push
//   2. 운영자가 본 화면에서 채널 등록 (channel_code + secret_ref + workflow 연결)
//   3. PUBLISHED 후 외부 업체에 endpoint URL + secret 공유
//   4. POST /v1/inbound/{channel_code} 로 push 도착 → audit.inbound_event INSERT
//   5. (Wave 6) workflow 자동 trigger
import {
  Copy,
  Globe,
  Pencil,
  Plus,
  RefreshCw,
  Send,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
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

const KIND_DESCRIPTIONS: Record<ChannelKind, string> = {
  WEBHOOK: "일반 외부 push (크롤링 결과 / 외부 시스템 통보 등)",
  FILE_UPLOAD: "사용자 multipart 업로드 (소상공인 / CSV/Excel 업로드)",
  OCR_RESULT: "외부 OCR 업체가 push 하는 인식 결과",
  CRAWLER_RESULT: "외부 크롤링 업체가 push 하는 수집 결과",
};

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

export function InboundChannelDesigner() {
  const domains = useDomains();
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
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Inbound Channel Designer</h2>
        <p className="text-sm text-muted-foreground">
          외부 시스템이 우리에게 push 하는 데이터 채널 등록 (Phase 7 Wave 1A).
          HMAC SHA256 + replay window ±5분. 공통 endpoint:{" "}
          <code className="text-xs">POST /v1/inbound/{"{channel_code}"}</code>
        </p>
      </div>

      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="text-xs text-muted-foreground">도메인</label>
              <select
                className="mt-1 h-9 w-48 rounded-md border bg-background px-3 text-sm"
                value={domainCode}
                onChange={(e) => setDomainCode(e.target.value)}
              >
                <option value="">전체</option>
                {domains.data?.map((d) => (
                  <option key={d.domain_code} value={d.domain_code}>
                    {d.domain_code} — {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">kind</label>
              <select
                className="mt-1 h-9 w-44 rounded-md border bg-background px-3 text-sm"
                value={kindFilter}
                onChange={(e) =>
                  setKindFilter((e.target.value || "") as ChannelKind | "")
                }
              >
                <option value="">전체</option>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">상태</label>
              <select
                className="mt-1 h-9 w-32 rounded-md border bg-background px-3 text-sm"
                value={statusFilter}
                onChange={(e) =>
                  setStatusFilter(
                    (e.target.value || "") as ChannelStatus | "",
                  )
                }
              >
                <option value="">전체</option>
                <option value="DRAFT">DRAFT</option>
                <option value="REVIEW">REVIEW</option>
                <option value="APPROVED">APPROVED</option>
                <option value="PUBLISHED">PUBLISHED</option>
              </select>
            </div>
            <div className="ml-auto">
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" />새 Inbound Channel
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {channels.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">
              불러오는 중...
            </div>
          )}
          {channels.error && (
            <div className="p-6 text-sm text-destructive">
              로드 실패: {(channels.error as Error).message}
            </div>
          )}
          {channels.data && channels.data.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              등록된 inbound channel 이 없습니다. 우측 상단 "+ 새 Inbound
              Channel" 로 등록.
            </div>
          )}
          {channels.data && channels.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>channel_code</Th>
                  <Th>도메인</Th>
                  <Th>kind</Th>
                  <Th>auth</Th>
                  <Th>workflow</Th>
                  <Th>활성</Th>
                  <Th>상태</Th>
                  <Th>업데이트</Th>
                  <Th>동작</Th>
                </Tr>
              </Thead>
              <Tbody>
                {channels.data.map((c) => (
                  <Tr key={c.channel_id}>
                    <Td>
                      <code className="text-xs">{c.channel_code}</code>
                    </Td>
                    <Td className="text-xs">{c.domain_code}</Td>
                    <Td>
                      <code className="text-xs">{c.channel_kind}</code>
                    </Td>
                    <Td className="text-xs">{c.auth_method}</Td>
                    <Td className="text-xs">
                      {c.workflow_id ? `#${c.workflow_id}` : "—"}
                    </Td>
                    <Td>
                      {c.is_active ? (
                        <Badge variant="success">on</Badge>
                      ) : (
                        <Badge variant="muted">off</Badge>
                      )}
                    </Td>
                    <Td>
                      <Badge variant={statusVariant(c.status)}>
                        {c.status}
                      </Badge>
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {formatDateTime(c.updated_at)}
                    </Td>
                    <Td>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(c)}
                      >
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
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <ChannelEditDialog
          mode="edit"
          open={!!editing}
          existing={editing}
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
  onClose: () => void;
}

function ChannelEditDialog({
  mode,
  open,
  existing,
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
    } else {
      setForm({
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
    }
  }, [mode, existing]);

  const isReadOnly = mode === "edit" && existing && existing.status !== "DRAFT";

  async function handleSubmit() {
    try {
      if (mode === "create") {
        await create.mutateAsync({
          ...form,
          description: form.description?.trim() || null,
          expected_content_type: form.expected_content_type?.trim() || null,
        });
        toast.success("Inbound Channel 등록 (DRAFT)");
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
          workflow_id: form.workflow_id,
        });
        toast.success("저장 완료");
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
      toast.success(`상태 전이: ${existing.status} → ${target}`);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`전이 실패: ${msg}`);
    }
  }

  async function handleDelete() {
    if (!existing) return;
    if (!confirm(`channel ${existing.channel_code} 을 삭제할까요?`)) return;
    try {
      await remove.mutateAsync(existing.channel_id);
      toast.success("삭제 완료");
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`삭제 실패: ${msg}`);
    }
  }

  function copyEndpoint() {
    const url = `${window.location.origin}/v1/inbound/${form.channel_code}`;
    navigator.clipboard.writeText(url);
    toast.success(`endpoint 복사됨: ${url}`);
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
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? "새 Inbound Channel"
              : `Channel ${existing?.channel_code} 편집`}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">
                channel_code
              </label>
              <Input
                value={form.channel_code}
                onChange={(e) =>
                  setForm({ ...form, channel_code: e.target.value })
                }
                disabled={mode === "edit"}
                placeholder="vendor_a_crawler"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">도메인</label>
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
                    {d.domain_code}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">kind</label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={form.channel_kind}
                onChange={(e) =>
                  setForm({
                    ...form,
                    channel_kind: e.target.value as ChannelKind,
                  })
                }
                disabled={mode === "edit"}
              >
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="rounded-md border border-border bg-muted/40 p-2 text-[11px]">
            💡 {KIND_DESCRIPTIONS[form.channel_kind]}
          </div>

          <div>
            <label className="text-xs text-muted-foreground">이름</label>
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="A 유통사 크롤링 결과 push"
            />
          </div>

          <div>
            <label className="text-xs text-muted-foreground">설명 (선택)</label>
            <Input
              value={form.description ?? ""}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              disabled={!!isReadOnly}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">
                auth_method
              </label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={form.auth_method}
                onChange={(e) =>
                  setForm({
                    ...form,
                    auth_method: e.target.value as AuthMethod,
                  })
                }
                disabled={mode === "edit"}
              >
                <option value="hmac_sha256">hmac_sha256</option>
                <option value="api_key" disabled>
                  api_key (Phase 7 Wave 1B+)
                </option>
                <option value="mtls" disabled>
                  mtls (Phase 7.5)
                </option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                secret_ref (env name)
              </label>
              <Input
                value={form.secret_ref}
                onChange={(e) =>
                  setForm({ ...form, secret_ref: e.target.value })
                }
                disabled={!!isReadOnly}
                placeholder="VENDOR_A_HMAC_SECRET"
              />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">
                expected_content_type
              </label>
              <Input
                value={form.expected_content_type ?? ""}
                onChange={(e) =>
                  setForm({ ...form, expected_content_type: e.target.value })
                }
                disabled={!!isReadOnly}
                placeholder="application/json"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                max_payload (B)
              </label>
              <Input
                type="number"
                value={form.max_payload_bytes ?? 10485760}
                onChange={(e) =>
                  setForm({
                    ...form,
                    max_payload_bytes: Number(e.target.value),
                  })
                }
                disabled={!!isReadOnly}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                rate_limit/min
              </label>
              <Input
                type="number"
                value={form.rate_limit_per_min ?? 100}
                onChange={(e) =>
                  setForm({
                    ...form,
                    rate_limit_per_min: Number(e.target.value),
                  })
                }
                disabled={!!isReadOnly}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">
                replay_window_sec
              </label>
              <Input
                type="number"
                min={30}
                max={3600}
                value={form.replay_window_sec ?? 300}
                onChange={(e) =>
                  setForm({
                    ...form,
                    replay_window_sec: Number(e.target.value),
                  })
                }
                disabled={!!isReadOnly}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                workflow_id (선택)
              </label>
              <Input
                type="number"
                value={form.workflow_id ?? ""}
                onChange={(e) =>
                  setForm({
                    ...form,
                    workflow_id: e.target.value ? Number(e.target.value) : null,
                  })
                }
                disabled={!!isReadOnly}
                placeholder="이벤트 trigger (Wave 6)"
              />
            </div>
          </div>

          {/* Endpoint URL preview + test instruction */}
          <div className="space-y-2 rounded-md border border-border p-3 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold uppercase text-muted-foreground">
                <Globe className="mr-1 inline h-3 w-3" />
                Endpoint (외부 업체에 공유)
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={copyEndpoint}
                disabled={!form.channel_code}
              >
                <Copy className="h-3 w-3" /> 복사
              </Button>
            </div>
            <code className="block break-all rounded bg-muted/40 p-2">
              POST {window.location.origin}/v1/inbound/
              {form.channel_code || "{channel_code}"}
            </code>
            <div className="text-[10px] text-muted-foreground">
              필수 헤더: <code>X-Signature: hmac-sha256={"<hex>"}</code>,{" "}
              <code>X-Timestamp: {"<unix epoch>"}</code>,{" "}
              <code>X-Idempotency-Key: {"<unique>"}</code>
            </div>
            <div className="text-[10px] text-muted-foreground">
              서명 대상:{" "}
              <code>HMAC-SHA256(secret, "${"{timestamp}"}.${"{body}"}")</code>{" "}
              hex
            </div>
          </div>

          {isReadOnly && existing && (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-xs">
              status={existing.status} — DRAFT 만 직접 수정 가능. PUBLISHED 만
              실제 inbound 수신 가능.
            </div>
          )}
        </div>

        <DialogFooter className="flex-wrap gap-2">
          {mode === "edit" && existing && (
            <>
              {transitionsFromCurrent.map((t) => (
                <Button
                  key={t}
                  variant="secondary"
                  size="sm"
                  onClick={() => handleTransition(t)}
                >
                  <Send className="h-3 w-3" />→ {t}
                </Button>
              ))}
              {existing.status !== "PUBLISHED" && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={handleDelete}
                >
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
