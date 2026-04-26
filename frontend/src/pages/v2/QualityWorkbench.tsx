// Phase 6 Wave 6 — Quality Workbench (workbench 6: DQ + Standardization 통합).
//
// § 13.1 결정에 따라 DQ Rule Builder + Standardization Designer 를 한 화면 2탭으로.
//
// 사용자 시나리오:
//   1. DQ 탭: 도메인/대상 mart 선택 → 6종 rule_kind 폼 (row_count_min /
//      null_pct_max / unique_columns / reference / range / custom_sql).
//      custom_sql 은 sql_guard + dry-run preview.
//   2. Standardization 탭: 도메인 → namespace 목록 → namespace 클릭 시
//      std_code_table 의 표준코드 목록 (read-only). alias 편집은 Phase 7 backlog.
import {
  AlertTriangle,
  Database,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { useDomains } from "@/api/v2/domains";
import {
  type DqRule,
  type DqRuleCreate,
  type DqRuleKind,
  type DqSeverity,
  type DqStatus,
  useCreateDqRule,
  useDqRules,
  usePreviewCustomSql,
  useUpdateDqRule,
} from "@/api/v2/dq_rules";
import { useNamespaceCodes, useNamespaces } from "@/api/v2/namespaces";
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
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

type Tab = "dq" | "stdz";

const RULE_KINDS: DqRuleKind[] = [
  "row_count_min",
  "null_pct_max",
  "unique_columns",
  "reference",
  "range",
  "custom_sql",
];

const SEVERITIES: DqSeverity[] = ["INFO", "WARN", "ERROR", "BLOCK"];

function statusVariant(
  s: DqStatus,
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

function severityVariant(
  s: DqSeverity,
): "default" | "secondary" | "success" | "warning" | "muted" | "destructive" {
  switch (s) {
    case "INFO":
      return "muted";
    case "WARN":
      return "warning";
    case "ERROR":
      return "destructive";
    case "BLOCK":
      return "destructive";
  }
}

export function QualityWorkbench() {
  const [tab, setTab] = useState<Tab>("dq");

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Quality Workbench (workbench 6)</h2>
        <p className="text-sm text-muted-foreground">
          데이터 품질 검증 (DQ) + 표준코드 매칭 (Standardization). 두 자산은 ETL
          캔버스에서 DQ_CHECK / STANDARDIZE 박스가 사용.
        </p>
      </div>

      <div className="flex gap-1 border-b border-border">
        <TabButton
          active={tab === "dq"}
          onClick={() => setTab("dq")}
          icon={<ShieldCheck className="h-4 w-4" />}
          label="DQ Rules"
        />
        <TabButton
          active={tab === "stdz"}
          onClick={() => setTab("stdz")}
          icon={<Sparkles className="h-4 w-4" />}
          label="Standardization"
        />
      </div>

      {tab === "dq" && <DqTab />}
      {tab === "stdz" && <StandardizationTab />}
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}

function TabButton({ active, onClick, icon, label }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 border-b-2 px-3 py-2 text-sm transition",
        active
          ? "border-primary text-primary"
          : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Tab 1 — DQ Rules
// ---------------------------------------------------------------------------
function DqTab() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("");
  const [targetTable, setTargetTable] = useState("");
  const rules = useDqRules({
    domain_code: domainCode || undefined,
    target_table: targetTable || undefined,
  });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<DqRule | null>(null);

  return (
    <div className="space-y-4">
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
              <label className="text-xs text-muted-foreground">
                target_table
              </label>
              <Input
                className="w-60"
                value={targetTable}
                onChange={(e) => setTargetTable(e.target.value)}
                placeholder="agri_mart.kamis_price"
              />
            </div>
            <div className="ml-auto">
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" />새 DQ Rule
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {rules.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">
              불러오는 중...
            </div>
          )}
          {rules.error && (
            <div className="p-6 text-sm text-destructive">
              로드 실패: {(rules.error as Error).message}
            </div>
          )}
          {rules.data && rules.data.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              등록된 DQ rule 이 없습니다. 우측 상단 "+ 새 DQ Rule" 로 등록.
            </div>
          )}
          {rules.data && rules.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>#</Th>
                  <Th>도메인</Th>
                  <Th>target_table</Th>
                  <Th>kind</Th>
                  <Th>severity</Th>
                  <Th>설명</Th>
                  <Th>상태</Th>
                  <Th>업데이트</Th>
                  <Th>동작</Th>
                </Tr>
              </Thead>
              <Tbody>
                {rules.data.map((r) => (
                  <Tr key={r.rule_id}>
                    <Td className="text-xs text-muted-foreground">
                      {r.rule_id}
                    </Td>
                    <Td className="text-xs">{r.domain_code}</Td>
                    <Td>
                      <code className="text-xs">{r.target_table}</code>
                    </Td>
                    <Td>
                      <code className="text-xs">{r.rule_kind}</code>
                    </Td>
                    <Td>
                      <Badge variant={severityVariant(r.severity)}>
                        {r.severity}
                      </Badge>
                    </Td>
                    <Td className="max-w-xs truncate text-xs">
                      {r.description ?? "—"}
                    </Td>
                    <Td>
                      <Badge variant={statusVariant(r.status)}>{r.status}</Badge>
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {formatDateTime(r.updated_at)}
                    </Td>
                    <Td>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(r)}
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
        <DqRuleEditDialog
          mode="create"
          open={creating}
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <DqRuleEditDialog
          mode="edit"
          open={!!editing}
          existing={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

interface DqRuleEditDialogProps {
  mode: "create" | "edit";
  open: boolean;
  existing?: DqRule;
  onClose: () => void;
}

function DqRuleEditDialog({
  mode,
  open,
  existing,
  onClose,
}: DqRuleEditDialogProps) {
  const domains = useDomains();
  const create = useCreateDqRule();
  const update = useUpdateDqRule(existing?.rule_id ?? 0);
  const preview = usePreviewCustomSql();

  const [form, setForm] = useState<DqRuleCreate>({
    domain_code: "",
    target_table: "",
    rule_kind: "row_count_min",
    rule_json: { min: 1 },
    severity: "ERROR",
    timeout_ms: 30_000,
    sample_limit: 10,
    description: "",
  });
  const [ruleJsonText, setRuleJsonText] = useState("{}");
  const [previewResult, setPreviewResult] = useState<string | null>(null);

  useEffect(() => {
    if (mode === "edit" && existing) {
      setForm({
        domain_code: existing.domain_code,
        target_table: existing.target_table,
        rule_kind: existing.rule_kind,
        rule_json: existing.rule_json,
        severity: existing.severity,
        timeout_ms: existing.timeout_ms,
        sample_limit: existing.sample_limit,
        description: existing.description ?? "",
      });
      setRuleJsonText(JSON.stringify(existing.rule_json, null, 2));
    } else {
      const def = defaultRuleJson(form.rule_kind);
      setForm({
        domain_code: "",
        target_table: "",
        rule_kind: "row_count_min",
        rule_json: def,
        severity: "ERROR",
        timeout_ms: 30_000,
        sample_limit: 10,
        description: "",
      });
      setRuleJsonText(JSON.stringify(def, null, 2));
    }
    setPreviewResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, existing]);

  const isReadOnly = mode === "edit" && existing && existing.status !== "DRAFT";

  function setKind(kind: DqRuleKind) {
    const def = defaultRuleJson(kind);
    setForm({ ...form, rule_kind: kind, rule_json: def });
    setRuleJsonText(JSON.stringify(def, null, 2));
  }

  function commitRuleJson() {
    try {
      const parsed = ruleJsonText.trim() ? JSON.parse(ruleJsonText) : {};
      setForm({ ...form, rule_json: parsed });
    } catch {
      toast.error("rule_json 파싱 실패");
    }
  }

  async function handleSubmit() {
    commitRuleJson();
    try {
      if (mode === "create") {
        await create.mutateAsync({
          ...form,
          description: form.description?.trim() || null,
        });
        toast.success("DQ rule 등록 (DRAFT)");
        onClose();
      } else if (existing) {
        await update.mutateAsync({
          rule_json: form.rule_json,
          severity: form.severity,
          timeout_ms: form.timeout_ms,
          sample_limit: form.sample_limit,
          description: form.description?.trim() || null,
        });
        toast.success("저장 완료");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`저장 실패: ${msg}`);
    }
  }

  async function handlePreviewCustomSql() {
    if (form.rule_kind !== "custom_sql") return;
    const sql = (form.rule_json as { sql?: string })?.sql;
    if (!sql) {
      toast.error("rule_json.sql 이 비어있음");
      return;
    }
    if (!form.domain_code) {
      toast.error("domain_code 필요");
      return;
    }
    try {
      const res = await preview.mutateAsync({
        domain_code: form.domain_code,
        sql,
        sample_limit: form.sample_limit ?? 10,
      });
      if (res.is_valid) {
        setPreviewResult(
          `OK · row_count=${res.row_count ?? "?"} · ${res.duration_ms}ms`,
        );
        toast.success("custom_sql preview 통과");
      } else {
        setPreviewResult(`FAIL: ${res.error}`);
        toast.error(`preview 실패: ${res.error}`);
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`preview 실패: ${msg}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? "새 DQ Rule"
              : `DQ Rule #${existing?.rule_id} 편집`}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
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
            <div className="col-span-2">
              <label className="text-xs text-muted-foreground">
                target_table
              </label>
              <Input
                value={form.target_table}
                onChange={(e) =>
                  setForm({ ...form, target_table: e.target.value })
                }
                disabled={mode === "edit"}
                placeholder="agri_mart.kamis_price"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">rule_kind</label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={form.rule_kind}
                onChange={(e) => setKind(e.target.value as DqRuleKind)}
                disabled={mode === "edit"}
              >
                {RULE_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">severity</label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={form.severity}
                onChange={(e) =>
                  setForm({ ...form, severity: e.target.value as DqSeverity })
                }
                disabled={!!isReadOnly}
              >
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">
              rule_json — {form.rule_kind} 의 파라미터 (예시 자동 채워짐)
            </label>
            <textarea
              className="mt-1 h-32 w-full rounded-md border bg-background p-2 font-mono text-xs"
              value={ruleJsonText}
              onChange={(e) => setRuleJsonText(e.target.value)}
              onBlur={commitRuleJson}
              disabled={!!isReadOnly}
            />
            <RuleHint kind={form.rule_kind} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">
                timeout_ms
              </label>
              <Input
                type="number"
                value={form.timeout_ms ?? 30000}
                onChange={(e) =>
                  setForm({
                    ...form,
                    timeout_ms: Number(e.target.value) || 30000,
                  })
                }
                disabled={!!isReadOnly}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                sample_limit
              </label>
              <Input
                type="number"
                value={form.sample_limit ?? 10}
                onChange={(e) =>
                  setForm({
                    ...form,
                    sample_limit: Number(e.target.value) || 10,
                  })
                }
                disabled={!!isReadOnly}
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">설명 (선택)</label>
            <Input
              value={form.description ?? ""}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              disabled={!!isReadOnly}
              placeholder="이 rule 의 의미"
            />
          </div>

          {form.rule_kind === "custom_sql" && (
            <div className="space-y-2 rounded-md border border-border p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold uppercase text-muted-foreground">
                  custom_sql preview (sandbox + sql_guard)
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handlePreviewCustomSql}
                  disabled={preview.isPending}
                >
                  <Play className="h-3.5 w-3.5" />
                  Preview
                </Button>
              </div>
              {previewResult && (
                <div
                  className={cn(
                    "text-xs",
                    previewResult.startsWith("OK")
                      ? "text-green-600"
                      : "text-destructive",
                  )}
                >
                  {previewResult}
                </div>
              )}
              <p className="text-[10px] text-muted-foreground">
                rule_json 의 sql 키에 SELECT 문 입력 — schema 화이트리스트 통과
                필수.
              </p>
            </div>
          )}

          {isReadOnly && existing && (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-xs">
              <AlertTriangle className="mr-1 inline h-3 w-3" />
              status={existing.status} — DRAFT 만 직접 수정 가능. PUBLISHED 는
              새 version 으로 등록.
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            닫기
          </Button>
          {!isReadOnly && (
            <Button onClick={handleSubmit}>
              {mode === "create" ? "등록" : "저장"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function defaultRuleJson(kind: DqRuleKind): Record<string, unknown> {
  switch (kind) {
    case "row_count_min":
      return { min: 1 };
    case "null_pct_max":
      return { column: "unit_price", max_pct: 5.0 };
    case "unique_columns":
      return { columns: ["ymd", "item_code", "market_code"] };
    case "reference":
      return { column: "item_code", ref: "agri_mart.item_master.code" };
    case "range":
      return { column: "unit_price", min: 0, max: 10_000_000 };
    case "custom_sql":
      return {
        sql: "SELECT COUNT(*) FROM agri_mart.kamis_price WHERE unit_price IS NULL",
      };
  }
}

function RuleHint({ kind }: { kind: DqRuleKind }) {
  const hints: Record<DqRuleKind, string> = {
    row_count_min: "{min: 1}  // 최소 row 수",
    null_pct_max:
      "{column: 'unit_price', max_pct: 5.0}  // 해당 컬럼 NULL 비율 % 상한",
    unique_columns:
      "{columns: ['ymd', 'item_code']}  // 컬럼 조합 unique",
    reference:
      "{column: 'item_code', ref: 'mart.item_master.code'}  // FK-like 검증",
    range:
      "{column: 'unit_price', min: 0, max: 10000000}  // 값 범위",
    custom_sql:
      "{sql: 'SELECT ...'}  // SELECT 만 허용. row_count 가 0 이면 통과",
  };
  return (
    <p className="mt-1 text-[10px] text-muted-foreground font-mono">
      💡 {hints[kind]}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Tab 2 — Standardization
// ---------------------------------------------------------------------------
function StandardizationTab() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("");
  const namespaces = useNamespaces(domainCode || undefined);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const codes = useNamespaceCodes(selectedId);

  const selectedNs = useMemo(
    () => namespaces.data?.find((n) => n.namespace_id === selectedId) ?? null,
    [namespaces.data, selectedId],
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="text-xs text-muted-foreground">도메인</label>
              <select
                className="mt-1 h-9 w-48 rounded-md border bg-background px-3 text-sm"
                value={domainCode}
                onChange={(e) => {
                  setDomainCode(e.target.value);
                  setSelectedId(null);
                }}
              >
                <option value="">전체</option>
                {domains.data?.map((d) => (
                  <option key={d.domain_code} value={d.domain_code}>
                    {d.domain_code} — {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="ml-auto text-xs text-muted-foreground">
              ※ alias 편집은 Phase 7 backlog. 본 화면은 등록된 namespace 와
              표준코드 read-only 보기.
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-3 gap-4">
        <Card className="col-span-1">
          <CardContent className="space-y-1 p-2">
            <div className="px-2 py-1 text-xs font-semibold uppercase text-muted-foreground">
              Namespace ({namespaces.data?.length ?? 0})
            </div>
            {namespaces.isLoading && (
              <div className="px-2 py-1 text-xs text-muted-foreground">
                불러오는 중...
              </div>
            )}
            {namespaces.data?.length === 0 && (
              <div className="px-2 py-1 text-xs text-muted-foreground">
                등록된 namespace 가 없습니다.
              </div>
            )}
            {namespaces.data?.map((n) => (
              <button
                key={n.namespace_id}
                type="button"
                onClick={() => setSelectedId(n.namespace_id)}
                className={cn(
                  "flex w-full items-start gap-2 rounded-md border px-2 py-2 text-left text-xs transition",
                  selectedId === n.namespace_id
                    ? "border-primary bg-primary/10"
                    : "border-transparent hover:bg-secondary",
                )}
              >
                <Database className="mt-0.5 h-4 w-4 text-primary" />
                <div className="flex-1">
                  <div className="font-mono font-semibold">{n.name}</div>
                  <div className="text-[10px] text-muted-foreground">
                    {n.domain_code}
                    {n.std_code_table && ` · ${n.std_code_table}`}
                  </div>
                </div>
              </button>
            ))}
          </CardContent>
        </Card>

        <Card className="col-span-2">
          <CardContent className="space-y-3 p-4 text-sm">
            {!selectedNs && (
              <div className="text-xs text-muted-foreground">
                좌측에서 namespace 를 선택하세요.
              </div>
            )}
            {selectedNs && (
              <>
                <div>
                  <div className="text-xs font-semibold uppercase text-muted-foreground">
                    Namespace
                  </div>
                  <div className="mt-1 font-mono">
                    {selectedNs.domain_code} / {selectedNs.name}
                  </div>
                  {selectedNs.description && (
                    <div className="text-xs text-muted-foreground">
                      {selectedNs.description}
                    </div>
                  )}
                  {selectedNs.std_code_table && (
                    <div className="mt-1 text-xs">
                      std_code_table:{" "}
                      <code className="text-xs">
                        {selectedNs.std_code_table}
                      </code>
                    </div>
                  )}
                </div>

                <div>
                  <div className="text-xs font-semibold uppercase text-muted-foreground">
                    표준코드 ({codes.data?.length ?? 0})
                  </div>
                  {codes.isLoading && (
                    <div className="text-xs text-muted-foreground">
                      불러오는 중...
                    </div>
                  )}
                  {codes.error && (
                    <div className="text-xs text-destructive">
                      {(codes.error as Error).message}
                    </div>
                  )}
                  {codes.data && codes.data.length === 0 && (
                    <div className="text-xs text-muted-foreground">
                      표준코드가 없습니다 (std_code_table 미설정 또는 빈 테이블).
                    </div>
                  )}
                  {codes.data && codes.data.length > 0 && (
                    <Table>
                      <Thead>
                        <Tr>
                          <Th>std_code</Th>
                          <Th>display_name</Th>
                          <Th>description</Th>
                          <Th>order</Th>
                        </Tr>
                      </Thead>
                      <Tbody>
                        {codes.data.map((c) => (
                          <Tr key={c.std_code}>
                            <Td>
                              <code className="text-xs">{c.std_code}</code>
                            </Td>
                            <Td className="text-xs">
                              {c.display_name ?? "—"}
                            </Td>
                            <Td className="text-xs text-muted-foreground">
                              {c.description ?? "—"}
                            </Td>
                            <Td className="text-xs">
                              {c.sort_order ?? "—"}
                            </Td>
                          </Tr>
                        ))}
                      </Tbody>
                    </Table>
                  )}
                </div>
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
