// Phase 6 Wave 1 — Source/API Designer (workbench 1).
//
// 어떤 REST API 든 등록 가능. KAMIS 는 *예시 데이터* 일 뿐.
// 사용자가 폼 채우면 도커 / 통계청 / 식약처 / 회사 ERP / 외부 SaaS 모두 같은 흐름.
import { Pencil, PlayCircle, Plus, Send, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import {
  type AuthMethod,
  type ConnectorIn,
  type ConnectorStatus,
  type HttpMethod,
  type PaginationKind,
  type PublicApiConnector,
  type ResponseFormat,
  type TestCallResponse,
  useConnectors,
  useCreateConnector,
  useDeleteConnector,
  useTestCallConnector,
  useTransitionConnector,
  useUpdateConnector,
} from "@/api/v2/connectors";
import { useDomains } from "@/api/v2/domains";
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

const HTTP_METHODS: HttpMethod[] = ["GET", "POST"];
const AUTH_METHODS: AuthMethod[] = [
  "none",
  "query_param",
  "header",
  "basic",
  "bearer",
];
const PAGINATION_KINDS: PaginationKind[] = [
  "none",
  "page_number",
  "offset_limit",
  "cursor",
];
const RESPONSE_FORMATS: ResponseFormat[] = ["json", "xml"];

type ConnectorFormState = ConnectorIn;

const EMPTY_FORM: ConnectorFormState = {
  domain_code: "",
  resource_code: "",
  name: "",
  description: "",
  endpoint_url: "",
  http_method: "GET",
  auth_method: "none",
  auth_param_name: "",
  secret_ref: "",
  request_headers: {},
  query_template: {},
  body_template: null,
  pagination_kind: "none",
  pagination_config: {},
  response_format: "json",
  response_path: "",
  timeout_sec: 15,
  retry_max: 2,
  rate_limit_per_min: 60,
  schedule_cron: "",
  schedule_enabled: false,
};

function statusVariant(
  s: ConnectorStatus,
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

export function SourceApiDesigner() {
  const connectors = useConnectors({ limit: 100 });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<PublicApiConnector | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">Public API Connector (workbench 1)</h2>
          <p className="text-sm text-muted-foreground">
            어떤 REST API 든 *코딩 0줄* 로 등록. KAMIS / 식약처 / 통계청 / 회사 내부 API 모두 동일 폼.
          </p>
        </div>
        <Button onClick={() => setCreating(true)} data-testid="btn-create-connector">
          <Plus className="h-4 w-4" />
          새 API 등록
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {connectors.isLoading ? (
            <div className="p-6 text-sm text-muted-foreground">로딩…</div>
          ) : connectors.isError ? (
            <div className="p-6 text-sm text-destructive">
              조회 실패: {(connectors.error as Error).message}
            </div>
          ) : !connectors.data || connectors.data.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground">
              등록된 API 가 없습니다. 우측 상단 *새 API 등록* 으로 시작.
            </div>
          ) : (
            <Table>
              <Thead>
                <Tr>
                  <Th>이름</Th>
                  <Th>도메인 / 리소스</Th>
                  <Th>Endpoint</Th>
                  <Th>Auth</Th>
                  <Th>상태</Th>
                  <Th>수집 주기</Th>
                  <Th>업데이트</Th>
                  <Th>동작</Th>
                </Tr>
              </Thead>
              <Tbody>
                {connectors.data.map((c) => (
                  <Tr key={c.connector_id}>
                    <Td>
                      <div className="font-medium">{c.name}</div>
                      {c.description && (
                        <div className="text-xs text-muted-foreground">
                          {c.description}
                        </div>
                      )}
                    </Td>
                    <Td>
                      <span className="font-mono text-xs">
                        {c.domain_code} / {c.resource_code}
                      </span>
                    </Td>
                    <Td>
                      <span className="font-mono text-xs">{c.endpoint_url}</span>
                    </Td>
                    <Td>
                      <Badge variant="muted">{c.auth_method}</Badge>
                      {c.auth_param_name && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          {c.auth_param_name}
                        </span>
                      )}
                    </Td>
                    <Td>
                      <Badge variant={statusVariant(c.status)}>{c.status}</Badge>
                    </Td>
                    <Td>
                      {c.schedule_cron ? (
                        <span className="font-mono text-xs">{c.schedule_cron}</span>
                      ) : (
                        <span className="text-xs text-muted-foreground">수동</span>
                      )}
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {formatDateTime(c.updated_at)}
                    </Td>
                    <Td>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(c)}
                        title="편집/테스트/발행"
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
        <ConnectorEditDialog
          open={creating}
          mode="create"
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <ConnectorEditDialog
          open={!!editing}
          mode="edit"
          existing={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

interface ConnectorEditDialogProps {
  open: boolean;
  mode: "create" | "edit";
  existing?: PublicApiConnector;
  onClose: () => void;
}

function ConnectorEditDialog({
  open,
  mode,
  existing,
  onClose,
}: ConnectorEditDialogProps) {
  const domains = useDomains();
  const create = useCreateConnector();
  const update = useUpdateConnector(existing?.connector_id ?? 0);
  const transition = useTransitionConnector(existing?.connector_id ?? 0);
  const remove = useDeleteConnector();
  const testCall = useTestCallConnector(existing?.connector_id ?? 0);

  const [form, setForm] = useState<ConnectorFormState>(EMPTY_FORM);
  const [headersText, setHeadersText] = useState<string>("{}");
  const [queryText, setQueryText] = useState<string>("{}");
  const [bodyText, setBodyText] = useState<string>("");
  const [paginationText, setPaginationText] = useState<string>("{}");
  const [testResult, setTestResult] = useState<TestCallResponse | null>(null);
  const [runtimeParamsText, setRuntimeParamsText] = useState<string>("{}");

  // 첫 로드 시 form 초기화.
  useEffect(() => {
    if (mode === "edit" && existing) {
      setForm({
        domain_code: existing.domain_code,
        resource_code: existing.resource_code,
        name: existing.name,
        description: existing.description ?? "",
        endpoint_url: existing.endpoint_url,
        http_method: existing.http_method,
        auth_method: existing.auth_method,
        auth_param_name: existing.auth_param_name ?? "",
        secret_ref: existing.secret_ref ?? "",
        request_headers: existing.request_headers,
        query_template: existing.query_template,
        body_template: existing.body_template,
        pagination_kind: existing.pagination_kind,
        pagination_config: existing.pagination_config,
        response_format: existing.response_format,
        response_path: existing.response_path ?? "",
        timeout_sec: existing.timeout_sec,
        retry_max: existing.retry_max,
        rate_limit_per_min: existing.rate_limit_per_min,
        schedule_cron: existing.schedule_cron ?? "",
        schedule_enabled: existing.schedule_enabled,
      });
      setHeadersText(JSON.stringify(existing.request_headers, null, 2));
      setQueryText(JSON.stringify(existing.query_template, null, 2));
      setBodyText(
        existing.body_template
          ? JSON.stringify(existing.body_template, null, 2)
          : "",
      );
      setPaginationText(JSON.stringify(existing.pagination_config, null, 2));
    } else {
      setForm(EMPTY_FORM);
      setHeadersText("{}");
      setQueryText("{}");
      setBodyText("");
      setPaginationText("{}");
    }
    setTestResult(null);
    setRuntimeParamsText("{}");
  }, [mode, existing]);

  const isReadOnly = useMemo(() => {
    if (mode === "create") return false;
    return existing?.status !== "DRAFT";
  }, [mode, existing]);

  function parseJsonField<T>(text: string, fieldName: string): T | undefined {
    if (!text || !text.trim()) return undefined;
    try {
      return JSON.parse(text) as T;
    } catch (e) {
      toast.error(`${fieldName} 은 유효한 JSON 이어야 합니다`);
      throw e;
    }
  }

  async function handleSubmit() {
    let request_headers: Record<string, string>;
    let query_template: Record<string, unknown>;
    let body_template: Record<string, unknown> | null;
    let pagination_config: Record<string, unknown>;
    try {
      request_headers =
        parseJsonField<Record<string, string>>(headersText, "request_headers") ?? {};
      query_template =
        parseJsonField<Record<string, unknown>>(queryText, "query_template") ?? {};
      body_template = bodyText.trim()
        ? (parseJsonField<Record<string, unknown>>(bodyText, "body_template") ?? null)
        : null;
      pagination_config =
        parseJsonField<Record<string, unknown>>(paginationText, "pagination_config") ??
        {};
    } catch {
      return;
    }

    const payload: ConnectorIn = {
      ...form,
      request_headers,
      query_template,
      body_template,
      pagination_config,
      auth_param_name: form.auth_param_name?.trim() || null,
      secret_ref: form.secret_ref?.trim() || null,
      response_path: form.response_path?.trim() || null,
      schedule_cron: form.schedule_cron?.trim() || null,
      description: form.description?.trim() || null,
    };

    try {
      if (mode === "create") {
        await create.mutateAsync(payload);
        toast.success("새 API 등록 완료 (DRAFT)");
        onClose();
      } else {
        await update.mutateAsync(payload);
        toast.success("저장 완료");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`저장 실패: ${msg}`);
    }
  }

  async function handleTest() {
    if (!existing) {
      toast.info("먼저 DRAFT 로 저장 후 테스트 호출 가능합니다");
      return;
    }
    let runtime_params: Record<string, unknown> = {};
    try {
      const parsed = parseJsonField<Record<string, unknown>>(
        runtimeParamsText,
        "runtime_params",
      );
      if (parsed) runtime_params = parsed;
    } catch {
      return;
    }
    try {
      const result = await testCall.mutateAsync({ runtime_params, max_pages: 1 });
      setTestResult(result);
      if (result.success) {
        toast.success(
          `호출 성공 — http=${result.http_status}, ${result.row_count}건 추출 (${result.duration_ms}ms)`,
        );
      } else {
        toast.error(`호출 실패: ${result.error_message ?? "unknown"}`);
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`테스트 호출 실패: ${msg}`);
    }
  }

  async function handleTransition(target: ConnectorStatus) {
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
    if (!confirm(`정말 '${existing.name}' connector 를 삭제할까요?`)) return;
    try {
      await remove.mutateAsync(existing.connector_id);
      toast.success("삭제 완료");
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`삭제 실패: ${msg}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? "새 Public API 등록"
              : `${existing?.name} (${existing?.status})`}
          </DialogTitle>
        </DialogHeader>

        {isReadOnly && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            DRAFT 상태에서만 직접 수정 가능합니다. APPROVED/PUBLISHED 는 새 버전을 생성해야
            합니다 (Phase 7 backlog).
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* 1. 기본 메타 */}
          <Section title="1. 기본">
            <FieldText
              label="API 이름"
              value={form.name}
              onChange={(v) => setForm({ ...form, name: v })}
              placeholder="KAMIS 도매시장 가격 / 식약처 의약품 / 통계청 KOSIS ..."
              disabled={isReadOnly}
              testid="field-name"
            />
            <FieldDropdown
              label="도메인"
              value={form.domain_code}
              options={
                (domains.data ?? []).map((d) => ({
                  value: d.domain_code,
                  label: `${d.domain_code} (${d.name})`,
                }))
              }
              onChange={(v) => setForm({ ...form, domain_code: v })}
              disabled={isReadOnly}
              testid="field-domain"
            />
            <FieldText
              label="리소스 코드"
              value={form.resource_code}
              onChange={(v) =>
                setForm({ ...form, resource_code: v.toUpperCase() })
              }
              placeholder="예: WHOLESALE_PRICE / DRUG_PRICE / KOSIS_STATS"
              disabled={isReadOnly}
              testid="field-resource"
            />
            <FieldText
              label="설명 (선택)"
              value={form.description ?? ""}
              onChange={(v) => setForm({ ...form, description: v })}
              disabled={isReadOnly}
            />
          </Section>

          {/* 2. HTTP */}
          <Section title="2. HTTP">
            <FieldText
              label="Endpoint URL"
              value={form.endpoint_url}
              onChange={(v) => setForm({ ...form, endpoint_url: v })}
              placeholder="http://example.gov.kr/api/v1/data"
              disabled={isReadOnly}
              testid="field-endpoint"
            />
            <FieldDropdown
              label="HTTP method"
              value={form.http_method ?? "GET"}
              options={HTTP_METHODS.map((m) => ({ value: m, label: m }))}
              onChange={(v) => setForm({ ...form, http_method: v as HttpMethod })}
              disabled={isReadOnly}
            />
            <div className="grid grid-cols-3 gap-2">
              <FieldNumber
                label="Timeout (sec)"
                value={form.timeout_sec ?? 15}
                onChange={(v) => setForm({ ...form, timeout_sec: v })}
                disabled={isReadOnly}
              />
              <FieldNumber
                label="Retry max"
                value={form.retry_max ?? 2}
                onChange={(v) => setForm({ ...form, retry_max: v })}
                disabled={isReadOnly}
              />
              <FieldNumber
                label="Rate / min"
                value={form.rate_limit_per_min ?? 60}
                onChange={(v) => setForm({ ...form, rate_limit_per_min: v })}
                disabled={isReadOnly}
              />
            </div>
          </Section>

          {/* 3. Auth */}
          <Section title="3. 인증">
            <FieldDropdown
              label="Auth 방식"
              value={form.auth_method ?? "none"}
              options={AUTH_METHODS.map((m) => ({ value: m, label: m }))}
              onChange={(v) => setForm({ ...form, auth_method: v as AuthMethod })}
              disabled={isReadOnly}
              testid="field-auth-method"
            />
            <FieldText
              label="Auth 파라미터 이름"
              value={form.auth_param_name ?? ""}
              onChange={(v) => setForm({ ...form, auth_param_name: v })}
              placeholder="예: cert_key / serviceKey / Authorization"
              disabled={isReadOnly || form.auth_method === "none"}
            />
            <FieldText
              label="Secret 참조 (env 이름)"
              value={form.secret_ref ?? ""}
              onChange={(v) => setForm({ ...form, secret_ref: v })}
              placeholder="예: KAMIS_CERT_KEY / DATAGO_KEY (값은 .env 에)"
              disabled={isReadOnly || form.auth_method === "none"}
            />
            <FieldJson
              label="Request headers (JSON)"
              value={headersText}
              onChange={setHeadersText}
              placeholder='{"Accept": "application/json"}'
              disabled={isReadOnly}
              rows={3}
            />
          </Section>

          {/* 4. Query / Body */}
          <Section title="4. Query / Body 템플릿">
            <FieldJson
              label="Query 템플릿 (JSON)"
              value={queryText}
              onChange={setQueryText}
              placeholder='{"date": "{ymd}", "page": "{page}"}'
              disabled={isReadOnly}
              rows={6}
              testid="field-query-template"
            />
            <p className="text-xs text-muted-foreground">
              템플릿 변수: <code>{"{ymd}"}</code> <code>{"{page}"}</code>{" "}
              <code>{"{cursor}"}</code>{" "}
              + 임의 키 (runtime_params 로 주입)
            </p>
            {form.http_method === "POST" && (
              <FieldJson
                label="Body 템플릿 (JSON, POST 만)"
                value={bodyText}
                onChange={setBodyText}
                placeholder='{"address": "{addr}"}'
                disabled={isReadOnly}
                rows={4}
              />
            )}
          </Section>

          {/* 5. Pagination */}
          <Section title="5. Pagination">
            <FieldDropdown
              label="Pagination 종류"
              value={form.pagination_kind ?? "none"}
              options={PAGINATION_KINDS.map((p) => ({ value: p, label: p }))}
              onChange={(v) =>
                setForm({ ...form, pagination_kind: v as PaginationKind })
              }
              disabled={isReadOnly}
            />
            {form.pagination_kind !== "none" && (
              <FieldJson
                label="Pagination 설정 (JSON)"
                value={paginationText}
                onChange={setPaginationText}
                placeholder={
                  form.pagination_kind === "page_number"
                    ? '{"page_param_name":"page", "page_size":100, "start_page":1}'
                    : form.pagination_kind === "offset_limit"
                      ? '{"offset_param_name":"offset","limit":100}'
                      : '{"cursor_param_name":"cursor","cursor_response_path":"$.next"}'
                }
                disabled={isReadOnly}
                rows={4}
              />
            )}
          </Section>

          {/* 6. Response */}
          <Section title="6. Response">
            <FieldDropdown
              label="응답 형식"
              value={form.response_format ?? "json"}
              options={RESPONSE_FORMATS.map((f) => ({ value: f, label: f }))}
              onChange={(v) =>
                setForm({ ...form, response_format: v as ResponseFormat })
              }
              disabled={isReadOnly}
            />
            <FieldText
              label="Response 추출 경로 (JSONPath-lite)"
              value={form.response_path ?? ""}
              onChange={(v) => setForm({ ...form, response_path: v })}
              placeholder="예: $.response.body.items.item / $.data.records[*]"
              disabled={isReadOnly}
              testid="field-response-path"
            />
          </Section>

          {/* 7. Schedule */}
          <Section title="7. 수집 주기">
            <FieldText
              label="Cron 표현식 (선택)"
              value={form.schedule_cron ?? ""}
              onChange={(v) => setForm({ ...form, schedule_cron: v })}
              placeholder="예: 0 9 * * * (매일 9시)"
              disabled={isReadOnly}
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.schedule_enabled ?? false}
                onChange={(e) =>
                  setForm({ ...form, schedule_enabled: e.target.checked })
                }
                disabled={isReadOnly}
              />
              <span>스케줄 활성화 (PUBLISHED 후 자동 polling)</span>
            </label>
          </Section>

          {/* 8. Test 호출 */}
          {mode === "edit" && existing && (
            <Section title="8. 테스트 호출 (실 API 사이드 이펙트 있음)">
              <FieldJson
                label="Runtime params (JSON)"
                value={runtimeParamsText}
                onChange={setRuntimeParamsText}
                placeholder='{"ymd": "2026-04-26"}'
                rows={3}
              />
              <Button
                variant="secondary"
                onClick={handleTest}
                disabled={testCall.isPending}
                data-testid="btn-test-call"
              >
                <PlayCircle className="h-4 w-4" />
                {testCall.isPending ? "호출 중…" : "테스트 호출"}
              </Button>
              {testResult && <TestResultView result={testResult} />}
            </Section>
          )}
        </div>

        <DialogFooter className="flex-wrap gap-2">
          {mode === "edit" && existing && (
            <>
              {existing.status === "DRAFT" && (
                <Button
                  variant="secondary"
                  onClick={() => handleTransition("REVIEW")}
                >
                  REVIEW 요청
                </Button>
              )}
              {existing.status === "REVIEW" && (
                <>
                  <Button onClick={() => handleTransition("APPROVED")}>
                    승인
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => handleTransition("DRAFT")}
                  >
                    돌려보내기
                  </Button>
                </>
              )}
              {existing.status === "APPROVED" && (
                <Button onClick={() => handleTransition("PUBLISHED")}>
                  <Send className="h-4 w-4" /> PUBLISHED 발행
                </Button>
              )}
              {existing.status !== "PUBLISHED" && (
                <Button
                  variant="destructive"
                  onClick={handleDelete}
                  disabled={remove.isPending}
                >
                  <Trash2 className="h-4 w-4" /> 삭제
                </Button>
              )}
            </>
          )}
          <Button variant="ghost" onClick={onClose}>
            닫기
          </Button>
          {!isReadOnly && (
            <Button
              onClick={handleSubmit}
              disabled={create.isPending || update.isPending}
              data-testid="btn-save-connector"
            >
              {mode === "create" ? "DRAFT 생성" : "저장"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// 작은 form helpers
// ---------------------------------------------------------------------------
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2 rounded-md border border-border p-3">
      <div className="text-sm font-semibold">{title}</div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

interface FieldTextProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  testid?: string;
}
function FieldText({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  testid,
}: FieldTextProps) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        data-testid={testid}
      />
    </label>
  );
}

interface FieldNumberProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}
function FieldNumber({ label, value, onChange, disabled }: FieldNumberProps) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        disabled={disabled}
      />
    </label>
  );
}

interface FieldDropdownProps {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  disabled?: boolean;
  testid?: string;
}
function FieldDropdown({
  label,
  value,
  options,
  onChange,
  disabled,
  testid,
}: FieldDropdownProps) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <select
        className="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        data-testid={testid}
      >
        <option value="">— 선택 —</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

interface FieldJsonProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
  testid?: string;
}
function FieldJson({
  label,
  value,
  onChange,
  placeholder,
  disabled,
  rows = 4,
  testid,
}: FieldJsonProps) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <textarea
        className="flex w-full rounded-md border border-input bg-background px-3 py-1 text-sm font-mono shadow-sm disabled:cursor-not-allowed disabled:opacity-50"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        rows={rows}
        data-testid={testid}
      />
    </label>
  );
}

function TestResultView({ result }: { result: TestCallResponse }) {
  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3 text-xs">
      <div className="flex flex-wrap gap-2">
        <Badge variant={result.success ? "default" : "destructive"}>
          {result.success ? "SUCCESS" : "FAIL"}
        </Badge>
        {result.http_status != null && (
          <Badge variant="muted">HTTP {result.http_status}</Badge>
        )}
        <Badge variant="muted">{result.row_count}건</Badge>
        <Badge variant="muted">{result.duration_ms}ms</Badge>
      </div>
      {result.error_message && (
        <div className="text-destructive">{result.error_message}</div>
      )}
      {result.sample_rows.length > 0 && (
        <div>
          <div className="mb-1 font-semibold">샘플 row (앞 10건):</div>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded bg-background p-2 text-[11px]">
            {JSON.stringify(result.sample_rows, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
