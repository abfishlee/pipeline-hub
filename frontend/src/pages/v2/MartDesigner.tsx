// Phase 6 Wave 3 — Mart Workbench (workbench 4: Mart + Load Policy 통합).
//
// 사용자 시나리오 (§ 13.1 결정):
//   1. 도메인 + resource 선택 (또는 새 mart 설계)
//   2. 컬럼 / PK / partition / index 폼 → DDL 자동 생성 + diff 미리보기
//   3. DRAFT 저장 (mart_design_draft) + transition (DRAFT→REVIEW→APPROVED→PUBLISHED)
//   4. 같은 화면 하단: load_policy 폼 (mode/key_columns/chunk_size) → DRAFT 저장
//   5. dry-run (rows_affected 추정)
import {
  Database,
  HardDrive,
  Pencil,
  Play,
  Plus,
  Save,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { useDomains } from "@/api/v2/domains";
import {
  type LoadPolicy,
  type LoadPolicyIn,
  type LoadPolicyMode,
  type LoadPolicyStatus,
  useCreateLoadPolicy,
  useDeleteLoadPolicy,
  useDryRunLoadTarget,
  useLoadPolicies,
  useTransitionLoadPolicy,
  useUpdateLoadPolicy,
} from "@/api/v2/load_policies";
import { MartTemplates, type MartTemplate } from "@/components/mart/MartTemplates";
import {
  type MartColumnSpec,
  type MartDraft,
  type MartIndexSpec,
  type MartStatus,
  useDeleteMartDraft,
  useDryRunMartDesigner,
  useMartDrafts,
  useTransitionMartDraft,
} from "@/api/v2/mart_drafts";
import { useResources } from "@/api/v2/resources";
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

const ALLOWED_TYPES = [
  "TEXT",
  "VARCHAR",
  "INTEGER",
  "BIGINT",
  "SMALLINT",
  "NUMERIC",
  "REAL",
  "DOUBLE PRECISION",
  "BOOLEAN",
  "DATE",
  "TIMESTAMP",
  "TIMESTAMPTZ",
  "JSONB",
  "JSON",
  "UUID",
  "BYTEA",
];

type Tab = "mart" | "policy";

function martVariant(
  s: MartStatus,
): "default" | "secondary" | "success" | "warning" | "muted" | "destructive" {
  switch (s) {
    case "DRAFT":
      return "muted";
    case "REVIEW":
      return "warning";
    case "APPROVED":
      return "default";
    case "PUBLISHED":
      return "success";
    case "ROLLED_BACK":
      return "destructive";
  }
}

function policyVariant(
  s: LoadPolicyStatus,
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

export function MartDesigner() {
  const [tab, setTab] = useState<Tab>("mart");

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Mart Workbench (workbench 4)</h2>
        <p className="text-sm text-muted-foreground">
          mart 테이블 설계 (DDL) + 적재 정책 (load_policy) 을 한 화면에서 관리.
        </p>
      </div>

      <div className="flex gap-1 border-b border-border">
        <TabButton
          active={tab === "mart"}
          onClick={() => setTab("mart")}
          icon={<Database className="h-4 w-4" />}
          label="Mart Schema (DDL)"
        />
        <TabButton
          active={tab === "policy"}
          onClick={() => setTab("policy")}
          icon={<HardDrive className="h-4 w-4" />}
          label="Load Policy"
        />
      </div>

      {tab === "mart" && <MartTab />}
      {tab === "policy" && <PolicyTab />}
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
// Tab 1 — Mart Schema (DDL)
// ---------------------------------------------------------------------------
function MartTab() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("");
  const [statusFilter, setStatusFilter] = useState<MartStatus | "">("");
  const drafts = useMartDrafts({
    domain_code: domainCode || undefined,
    status: statusFilter || undefined,
  });
  const [creating, setCreating] = useState(false);
  const [viewing, setViewing] = useState<MartDraft | null>(null);

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
              <label className="text-xs text-muted-foreground">상태</label>
              <select
                className="mt-1 h-9 w-36 rounded-md border bg-background px-3 text-sm"
                value={statusFilter}
                onChange={(e) =>
                  setStatusFilter((e.target.value || "") as MartStatus | "")
                }
              >
                <option value="">전체</option>
                <option value="DRAFT">DRAFT</option>
                <option value="REVIEW">REVIEW</option>
                <option value="APPROVED">APPROVED</option>
                <option value="PUBLISHED">PUBLISHED</option>
                <option value="ROLLED_BACK">ROLLED_BACK</option>
              </select>
            </div>
            <div className="ml-auto">
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" />새 Mart 설계
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {drafts.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">불러오는 중...</div>
          )}
          {drafts.error && (
            <div className="p-6 text-sm text-destructive">
              로드 실패: {(drafts.error as Error).message}
            </div>
          )}
          {drafts.data && drafts.data.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              등록된 mart_design_draft 가 없습니다. 우측 상단 "+ 새 Mart 설계" 로 등록.
            </div>
          )}
          {drafts.data && drafts.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>#</Th>
                  <Th>도메인</Th>
                  <Th>target_table</Th>
                  <Th>diff kind</Th>
                  <Th>상태</Th>
                  <Th>업데이트</Th>
                  <Th>동작</Th>
                </Tr>
              </Thead>
              <Tbody>
                {drafts.data.map((d) => (
                  <Tr key={d.draft_id}>
                    <Td className="text-xs text-muted-foreground">
                      {d.draft_id}
                    </Td>
                    <Td className="text-xs">{d.domain_code}</Td>
                    <Td>
                      <code className="text-xs">{d.target_table}</code>
                    </Td>
                    <Td className="text-xs">
                      {(d.diff_summary as { kind?: string })?.kind ?? "—"}
                    </Td>
                    <Td>
                      <Badge variant={martVariant(d.status)}>{d.status}</Badge>
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {formatDateTime(d.updated_at)}
                    </Td>
                    <Td>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setViewing(d)}
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
        <MartDesignDialog open={creating} onClose={() => setCreating(false)} />
      )}
      {viewing && (
        <MartDraftDetailDialog
          open={!!viewing}
          draft={viewing}
          onClose={() => setViewing(null)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mart 설계 dialog (CREATE)
// ---------------------------------------------------------------------------
interface MartDesignDialogProps {
  open: boolean;
  onClose: () => void;
}

function MartDesignDialog({ open, onClose }: MartDesignDialogProps) {
  const domains = useDomains();
  const dryrun = useDryRunMartDesigner();

  const [domainCode, setDomainCode] = useState("");
  const [targetTable, setTargetTable] = useState("");
  const [description, setDescription] = useState("");
  const [columns, setColumns] = useState<MartColumnSpec[]>([
    { name: "ymd", type: "TEXT", nullable: false },
  ]);
  const [primaryKey, setPrimaryKey] = useState<string[]>([]);
  const [partitionKey, setPartitionKey] = useState("");
  const [indexes, setIndexes] = useState<MartIndexSpec[]>([]);
  const [saveAsDraft, setSaveAsDraft] = useState(true);

  const [ddlPreview, setDdlPreview] = useState<string | null>(null);
  const [diffPreview, setDiffPreview] = useState<Record<string, unknown> | null>(
    null,
  );

  function addColumn() {
    setColumns([...columns, { name: "", type: "TEXT", nullable: true }]);
  }
  function removeColumn(i: number) {
    setColumns(columns.filter((_, idx) => idx !== i));
  }
  function updateColumn(i: number, patch: Partial<MartColumnSpec>) {
    setColumns(columns.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));
  }

  function addIndex() {
    setIndexes([...indexes, { name: "", columns: [], unique: false }]);
  }
  function removeIndex(i: number) {
    setIndexes(indexes.filter((_, idx) => idx !== i));
  }
  function updateIndex(i: number, patch: Partial<MartIndexSpec>) {
    setIndexes(indexes.map((x, idx) => (idx === i ? { ...x, ...patch } : x)));
  }

  function togglePk(name: string) {
    setPrimaryKey(
      primaryKey.includes(name)
        ? primaryKey.filter((k) => k !== name)
        : [...primaryKey, name],
    );
  }

  function applyTemplate(t: MartTemplate) {
    // {domain} 토큰을 현재 도메인으로 치환
    const dom = domainCode || "agri";
    setTargetTable(t.example_target.replace("{domain}", dom));
    setDescription(t.description);
    setColumns(t.columns.map((c) => ({ ...c })));
    setPrimaryKey([...t.primary_key]);
    setPartitionKey(t.partition_key ?? "");
    setIndexes(t.indexes.map((i) => ({ ...i, columns: [...i.columns] })));
    toast.success(
      `템플릿 적용: ${t.label} (${t.columns.length} 컬럼, mode=${t.recommended_load_mode})`,
    );
  }

  async function runDryRun() {
    setDdlPreview(null);
    setDiffPreview(null);
    if (!domainCode || !targetTable || columns.length === 0) {
      toast.error("도메인 / target_table / 컬럼은 필수");
      return;
    }
    try {
      const res = await dryrun.mutateAsync({
        domain_code: domainCode,
        target_table: targetTable,
        columns,
        primary_key: primaryKey,
        partition_key: partitionKey || null,
        indexes,
        description: description || null,
        save_as_draft: saveAsDraft,
      });
      setDdlPreview(res.ddl_text);
      setDiffPreview(res.target_summary);
      toast.success(
        saveAsDraft
          ? `DDL 생성 + DRAFT 저장 (draft_id=${res.draft_id})`
          : "DDL 미리보기 (저장 X)",
      );
      if (saveAsDraft) {
        setTimeout(() => onClose(), 1200);
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`dry-run 실패: ${msg}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>새 Mart 설계 (DDL 자동 생성)</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <MartTemplates onSelect={applyTemplate} />

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">도메인</label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={domainCode}
                onChange={(e) => setDomainCode(e.target.value)}
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
                target_table (`schema.table`)
              </label>
              <Input
                value={targetTable}
                onChange={(e) => setTargetTable(e.target.value)}
                placeholder={
                  domainCode
                    ? `${domainCode}_mart.kamis_price`
                    : "agri_mart.kamis_price"
                }
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">설명 (선택)</label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="KAMIS 도매시장 가격 fact"
            />
          </div>

          {/* 컬럼 */}
          <div>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-sm font-semibold">컬럼</span>
              <Button variant="outline" size="sm" onClick={addColumn}>
                <Plus className="h-3.5 w-3.5" />컬럼 추가
              </Button>
            </div>
            <div className="space-y-1">
              {columns.map((c, i) => (
                <div
                  key={i}
                  className="grid grid-cols-12 gap-1 rounded-md border border-border p-2"
                >
                  <Input
                    className="col-span-3"
                    placeholder="name"
                    value={c.name}
                    onChange={(e) => updateColumn(i, { name: e.target.value })}
                  />
                  <select
                    className="col-span-2 h-9 rounded-md border bg-background px-2 text-sm"
                    value={c.type}
                    onChange={(e) => updateColumn(i, { type: e.target.value })}
                  >
                    {ALLOWED_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <label className="col-span-1 flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={c.nullable ?? true}
                      onChange={(e) =>
                        updateColumn(i, { nullable: e.target.checked })
                      }
                    />
                    NULL
                  </label>
                  <Input
                    className="col-span-2"
                    placeholder="default (선택)"
                    value={c.default ?? ""}
                    onChange={(e) =>
                      updateColumn(i, { default: e.target.value })
                    }
                  />
                  <label className="col-span-1 flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={primaryKey.includes(c.name)}
                      onChange={() => togglePk(c.name)}
                      disabled={!c.name}
                    />
                    PK
                  </label>
                  <Input
                    className="col-span-2"
                    placeholder="설명"
                    value={c.description ?? ""}
                    onChange={(e) =>
                      updateColumn(i, { description: e.target.value })
                    }
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="col-span-1"
                    onClick={() => removeColumn(i)}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          </div>

          {/* PK + Partition */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">
                PRIMARY KEY (위에서 PK 체크)
              </label>
              <div className="mt-1 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs">
                {primaryKey.length > 0 ? primaryKey.join(", ") : "— (없음)"}
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                PARTITION BY (선택)
              </label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={partitionKey}
                onChange={(e) => setPartitionKey(e.target.value)}
              >
                <option value="">— (없음)</option>
                {columns
                  .filter((c) => c.name)
                  .map((c) => (
                    <option key={c.name} value={c.name}>
                      {c.name}
                    </option>
                  ))}
              </select>
            </div>
          </div>

          {/* 인덱스 */}
          <div>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-sm font-semibold">인덱스</span>
              <Button variant="outline" size="sm" onClick={addIndex}>
                <Plus className="h-3.5 w-3.5" />인덱스 추가
              </Button>
            </div>
            {indexes.length === 0 && (
              <div className="text-xs text-muted-foreground">— (없음)</div>
            )}
            <div className="space-y-1">
              {indexes.map((idx, i) => (
                <div
                  key={i}
                  className="grid grid-cols-12 gap-1 rounded-md border border-border p-2"
                >
                  <Input
                    className="col-span-3"
                    placeholder="index name"
                    value={idx.name}
                    onChange={(e) => updateIndex(i, { name: e.target.value })}
                  />
                  <Input
                    className="col-span-7"
                    placeholder="cols (comma — e.g. market_code,ymd)"
                    value={idx.columns.join(",")}
                    onChange={(e) =>
                      updateIndex(i, {
                        columns: e.target.value
                          .split(",")
                          .map((s) => s.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                  <label className="col-span-1 flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={idx.unique ?? false}
                      onChange={(e) =>
                        updateIndex(i, { unique: e.target.checked })
                      }
                    />
                    UNIQUE
                  </label>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="col-span-1"
                    onClick={() => removeIndex(i)}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive" />
                  </Button>
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <input
              id="saveDraft"
              type="checkbox"
              checked={saveAsDraft}
              onChange={(e) => setSaveAsDraft(e.target.checked)}
            />
            <label htmlFor="saveDraft" className="text-xs">
              dry-run 후 mart_design_draft 에 DRAFT 저장
            </label>
          </div>

          {/* 결과 미리보기 */}
          {ddlPreview !== null && (
            <div className="space-y-2">
              <div className="text-xs font-semibold uppercase text-muted-foreground">
                DDL 미리보기
              </div>
              <pre className="max-h-60 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
                {ddlPreview}
              </pre>
              {diffPreview && (
                <div className="text-xs">
                  <span className="font-semibold">diff:</span>{" "}
                  <code className="text-xs">
                    {JSON.stringify(diffPreview, null, 0)}
                  </code>
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            닫기
          </Button>
          <Button onClick={runDryRun} disabled={dryrun.isPending}>
            <Play className="h-4 w-4" />
            {saveAsDraft ? "DDL 생성 + DRAFT 저장" : "DDL 미리보기 (저장 X)"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Mart draft 상세 (DDL 보기 + transition + 삭제)
// ---------------------------------------------------------------------------
interface MartDraftDetailDialogProps {
  open: boolean;
  draft: MartDraft;
  onClose: () => void;
}

function MartDraftDetailDialog({
  open,
  draft,
  onClose,
}: MartDraftDetailDialogProps) {
  const transition = useTransitionMartDraft(draft.draft_id);
  const remove = useDeleteMartDraft();

  const transitionsFromCurrent: MartStatus[] = useMemo(() => {
    switch (draft.status) {
      case "DRAFT":
        return ["REVIEW"];
      case "REVIEW":
        return ["APPROVED", "DRAFT"];
      case "APPROVED":
        return ["PUBLISHED", "DRAFT"];
      case "PUBLISHED":
        return ["DRAFT", "ROLLED_BACK"];
      case "ROLLED_BACK":
        return ["DRAFT"];
    }
  }, [draft.status]);

  async function handleTransition(target: MartStatus) {
    try {
      await transition.mutateAsync(target);
      toast.success(`상태 전이: ${draft.status} → ${target}`);
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`전이 실패: ${msg}`);
    }
  }

  async function handleDelete() {
    if (!confirm(`mart_draft #${draft.draft_id} 을 삭제할까요?`)) return;
    try {
      await remove.mutateAsync(draft.draft_id);
      toast.success("삭제 완료");
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`삭제 실패: ${msg}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            Mart Draft #{draft.draft_id} — {draft.target_table}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs">
            <Badge variant={martVariant(draft.status)}>{draft.status}</Badge>
            <span className="text-muted-foreground">
              도메인 = {draft.domain_code} · 업데이트 ={" "}
              {formatDateTime(draft.updated_at)}
            </span>
          </div>

          <div>
            <div className="text-xs font-semibold uppercase text-muted-foreground">
              DDL
            </div>
            <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
              {draft.ddl_text}
            </pre>
          </div>

          <div>
            <div className="text-xs font-semibold uppercase text-muted-foreground">
              diff_summary
            </div>
            <pre className="max-h-32 overflow-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
              {JSON.stringify(draft.diff_summary, null, 2)}
            </pre>
          </div>
        </div>

        <DialogFooter className="flex-wrap gap-2">
          {transitionsFromCurrent.map((t) => (
            <Button
              key={t}
              variant="secondary"
              size="sm"
              onClick={() => handleTransition(t)}
            >
              → {t}
            </Button>
          ))}
          {draft.status !== "PUBLISHED" && (
            <Button variant="destructive" size="sm" onClick={handleDelete}>
              삭제
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>
            닫기
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Tab 2 — Load Policy
// ---------------------------------------------------------------------------
function PolicyTab() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("");
  const [statusFilter, setStatusFilter] = useState<LoadPolicyStatus | "">("");
  const resources = useResources({
    domain_code: domainCode || undefined,
  });
  const [resourceId, setResourceId] = useState<number | null>(null);
  const policies = useLoadPolicies({
    resource_id: resourceId ?? undefined,
    status: statusFilter || undefined,
  });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<LoadPolicy | null>(null);

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
                  setResourceId(null);
                }}
              >
                <option value="">전체</option>
                {domains.data?.map((d) => (
                  <option key={d.domain_code} value={d.domain_code}>
                    {d.domain_code}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">resource</label>
              <select
                className="mt-1 h-9 w-64 rounded-md border bg-background px-3 text-sm"
                value={resourceId ?? ""}
                onChange={(e) =>
                  setResourceId(e.target.value ? Number(e.target.value) : null)
                }
              >
                <option value="">전체</option>
                {resources.data?.map((r) => (
                  <option key={r.resource_id} value={r.resource_id}>
                    #{r.resource_id} {r.domain_code}/{r.resource_code} v
                    {r.version}
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
                    (e.target.value || "") as LoadPolicyStatus | "",
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
                <Plus className="h-4 w-4" />새 Load Policy
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {policies.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">불러오는 중...</div>
          )}
          {policies.error && (
            <div className="p-6 text-sm text-destructive">
              로드 실패: {(policies.error as Error).message}
            </div>
          )}
          {policies.data && policies.data.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              등록된 load_policy 가 없습니다.
            </div>
          )}
          {policies.data && policies.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>policy_id</Th>
                  <Th>resource_id</Th>
                  <Th>v</Th>
                  <Th>mode</Th>
                  <Th>key_columns</Th>
                  <Th>chunk</Th>
                  <Th>상태</Th>
                  <Th>업데이트</Th>
                  <Th>동작</Th>
                </Tr>
              </Thead>
              <Tbody>
                {policies.data.map((p) => (
                  <Tr key={p.policy_id}>
                    <Td className="text-xs text-muted-foreground">
                      {p.policy_id}
                    </Td>
                    <Td className="text-xs">{p.resource_id}</Td>
                    <Td className="text-xs text-muted-foreground">
                      v{p.version}
                    </Td>
                    <Td>
                      <code className="text-xs">{p.mode}</code>
                    </Td>
                    <Td>
                      <code className="text-xs">
                        {p.key_columns.length > 0
                          ? p.key_columns.join(", ")
                          : "—"}
                      </code>
                    </Td>
                    <Td className="text-xs">{p.chunk_size}</Td>
                    <Td>
                      <Badge variant={policyVariant(p.status)}>{p.status}</Badge>
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {formatDateTime(p.updated_at)}
                    </Td>
                    <Td>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(p)}
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
        <PolicyEditDialog
          mode="create"
          open={creating}
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <PolicyEditDialog
          mode="edit"
          open={!!editing}
          existing={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

interface PolicyEditDialogProps {
  mode: "create" | "edit";
  open: boolean;
  existing?: LoadPolicy;
  onClose: () => void;
}

function PolicyEditDialog({
  mode,
  open,
  existing,
  onClose,
}: PolicyEditDialogProps) {
  const resources = useResources();
  const create = useCreateLoadPolicy();
  const update = useUpdateLoadPolicy(existing?.policy_id ?? 0);
  const transition = useTransitionLoadPolicy(existing?.policy_id ?? 0);
  const remove = useDeleteLoadPolicy();
  const dryrun = useDryRunLoadTarget();

  const [form, setForm] = useState<LoadPolicyIn>({
    resource_id: 0,
    mode: "append_only",
    key_columns: [],
    partition_expr: "",
    chunk_size: 1000,
    statement_timeout_ms: 60_000,
    version: 1,
  });

  const [keysInput, setKeysInput] = useState("");
  const [sourceTableForDryRun, setSourceTableForDryRun] = useState("");

  useEffect(() => {
    if (mode === "edit" && existing) {
      setForm({
        resource_id: existing.resource_id,
        mode: existing.mode,
        key_columns: existing.key_columns,
        partition_expr: existing.partition_expr ?? "",
        chunk_size: existing.chunk_size,
        statement_timeout_ms: existing.statement_timeout_ms,
        version: existing.version,
      });
      setKeysInput(existing.key_columns.join(", "));
    } else {
      setForm({
        resource_id: 0,
        mode: "append_only",
        key_columns: [],
        partition_expr: "",
        chunk_size: 1000,
        statement_timeout_ms: 60_000,
        version: 1,
      });
      setKeysInput("");
    }
  }, [mode, existing]);

  const isReadOnly = mode === "edit" && existing && existing.status !== "DRAFT";

  function parseKeys(input: string): string[] {
    return input
      .split(",")
      .map((k) => k.trim())
      .filter(Boolean);
  }

  async function handleSubmit() {
    const keys = parseKeys(keysInput);
    try {
      if (mode === "create") {
        await create.mutateAsync({
          ...form,
          key_columns: keys,
          partition_expr: form.partition_expr?.trim() || null,
        });
        toast.success("Load Policy 등록 (DRAFT)");
        onClose();
      } else {
        await update.mutateAsync({
          mode: form.mode,
          key_columns: keys,
          partition_expr: form.partition_expr?.trim() || null,
          chunk_size: form.chunk_size,
          statement_timeout_ms: form.statement_timeout_ms,
        });
        toast.success("저장 완료");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`저장 실패: ${msg}`);
    }
  }

  async function handleTransition(target: LoadPolicyStatus) {
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
    if (!confirm(`load_policy #${existing.policy_id} 을 삭제할까요?`)) return;
    try {
      await remove.mutateAsync(existing.policy_id);
      toast.success("삭제 완료");
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`삭제 실패: ${msg}`);
    }
  }

  async function handleDryRun() {
    if (!existing) return;
    if (!sourceTableForDryRun) {
      toast.error("source_table 입력 필요 (예: agri_stg.cleaned_2026_04)");
      return;
    }
    const res = resources.data?.find((r) => r.resource_id === existing.resource_id);
    try {
      const out = await dryrun.mutateAsync({
        domain_code: res?.domain_code ?? "",
        source_table: sourceTableForDryRun,
        policy_id: existing.policy_id,
        resource_id: existing.resource_id,
      });
      const rows = out.rows_affected[0] ?? 0;
      toast.success(
        `dry-run 완료 — rows_affected≈${rows} · errors=${out.errors.length}`,
      );
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`dry-run 실패: ${msg}`);
    }
  }

  const transitionsFromCurrent: LoadPolicyStatus[] = useMemo(() => {
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

  const isAdvancedMode = form.mode === "scd_type_2" || form.mode === "current_snapshot";

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? "새 Load Policy"
              : `Load Policy #${existing?.policy_id} 편집`}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground">resource</label>
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
              value={form.resource_id || ""}
              onChange={(e) =>
                setForm({ ...form, resource_id: Number(e.target.value) || 0 })
              }
              disabled={mode === "edit"}
            >
              <option value="">선택</option>
              {resources.data?.map((r) => (
                <option key={r.resource_id} value={r.resource_id}>
                  #{r.resource_id} {r.domain_code}/{r.resource_code} v{r.version}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">mode</label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={form.mode}
                onChange={(e) =>
                  setForm({ ...form, mode: e.target.value as LoadPolicyMode })
                }
                disabled={!!isReadOnly}
              >
                <option value="append_only">append_only</option>
                <option value="upsert">upsert</option>
                <option value="scd_type_2">scd_type_2 (Phase 7+)</option>
                <option value="current_snapshot">
                  current_snapshot (Phase 7+)
                </option>
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">version</label>
              <Input
                type="number"
                min={1}
                value={form.version ?? 1}
                onChange={(e) =>
                  setForm({ ...form, version: Number(e.target.value) || 1 })
                }
                disabled={mode === "edit"}
              />
            </div>
          </div>

          {isAdvancedMode && (
            <div className="rounded-md border border-warning bg-warning/10 p-2 text-xs">
              ⚠ scd_type_2 / current_snapshot 모드는 Phase 7 backlog.
              저장은 가능하지만 LOAD_TARGET 노드 실행은 아직 지원하지 않습니다.
            </div>
          )}

          <div>
            <label className="text-xs text-muted-foreground">
              key_columns (mode≠append_only 필수, comma)
            </label>
            <Input
              value={keysInput}
              onChange={(e) => setKeysInput(e.target.value)}
              disabled={!!isReadOnly}
              placeholder="ymd, item_code, market_code"
            />
          </div>

          <div>
            <label className="text-xs text-muted-foreground">
              partition_expr (선택)
            </label>
            <Input
              value={form.partition_expr ?? ""}
              onChange={(e) =>
                setForm({ ...form, partition_expr: e.target.value })
              }
              disabled={!!isReadOnly}
              placeholder="ymd"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">chunk_size</label>
              <Input
                type="number"
                min={1}
                max={100000}
                value={form.chunk_size ?? 1000}
                onChange={(e) =>
                  setForm({
                    ...form,
                    chunk_size: Number(e.target.value) || 1000,
                  })
                }
                disabled={!!isReadOnly}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                statement_timeout_ms
              </label>
              <Input
                type="number"
                min={100}
                max={600000}
                value={form.statement_timeout_ms ?? 60000}
                onChange={(e) =>
                  setForm({
                    ...form,
                    statement_timeout_ms: Number(e.target.value) || 60000,
                  })
                }
                disabled={!!isReadOnly}
              />
            </div>
          </div>

          {mode === "edit" && existing && (
            <div className="space-y-2 rounded-md border border-border p-3">
              <div className="text-xs font-semibold uppercase text-muted-foreground">
                Dry-run (rollback)
              </div>
              <div className="flex gap-2">
                <Input
                  value={sourceTableForDryRun}
                  onChange={(e) => setSourceTableForDryRun(e.target.value)}
                  placeholder="source_table — 예: agri_stg.cleaned_2026_04"
                />
                <Button onClick={handleDryRun} disabled={dryrun.isPending}>
                  <Play className="h-4 w-4" />
                  Dry-run
                </Button>
              </div>
            </div>
          )}

          {isReadOnly && existing && (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-xs">
              status={existing.status} — DRAFT 만 직접 수정. APPROVED/PUBLISHED 는
              새 version 으로 등록.
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
                  → {t}
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
              <Save className="h-4 w-4" />
              {mode === "create" ? "등록" : "저장"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
