// Phase 6 Wave 2A — Field Mapping Designer (workbench 2 코어).
//
// 사용자 시나리오:
//   1. contract 선택 (등록된 source_contract 중)
//   2. target table 선택 (자동 inferred 또는 수동)
//   3. 매핑 행 추가 — source_path → target_column [+ transform_expr]
//   4. 함수 도움말 (drawer) — 26+ allowlist 함수 검색/선택
//   5. dry-run → row_count + sample + errors
//   6. 상태머신 — DRAFT → REVIEW → APPROVED → PUBLISHED
import {
  Code2,
  Pencil,
  Plus,
  Send,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { useDomains } from "@/api/v2/domains";
import {
  type ContractLight,
  type FieldMapping,
  type FieldMappingIn,
  type FunctionSpec,
  type MappingStatus,
  type TableColumn,
  useContractsLight,
  useCreateMapping,
  useDeleteMapping,
  useDryRunFieldMapping,
  useFunctionRegistry,
  useMappings,
  useTableColumns,
  useTransitionMapping,
  useUpdateMapping,
} from "@/api/v2/mappings";
import { JsonPathPicker } from "@/components/mapping/JsonPathPicker";
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

function statusVariant(
  s: MappingStatus,
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

export function FieldMappingDesigner() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState<string>("");
  const [contractId, setContractId] = useState<number | null>(null);

  const contracts = useContractsLight(domainCode || undefined);
  const mappings = useMappings({
    contract_id: contractId ?? undefined,
  });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<FieldMapping | null>(null);
  const [showFunctions, setShowFunctions] = useState(false);
  const [dryRunOpen, setDryRunOpen] = useState(false);

  const selectedContract: ContractLight | undefined = useMemo(
    () => contracts.data?.find((c) => c.contract_id === contractId),
    [contracts.data, contractId],
  );

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Field Mapping Designer (workbench 2)</h2>
        <p className="text-sm text-muted-foreground">
          source 응답의 필드를 target mart 컬럼에 매핑. transform_expr 로 26+ 함수 적용 가능.
        </p>
      </div>

      {/* Step 1 — contract 선택 */}
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="space-y-1">
              <span className="text-xs text-muted-foreground">도메인 (필터)</span>
              <select
                className="flex h-9 w-48 rounded-md border border-input bg-background px-3 text-sm"
                value={domainCode}
                onChange={(e) => {
                  setDomainCode(e.target.value);
                  setContractId(null);
                }}
                data-testid="filter-domain"
              >
                <option value="">— 전체 —</option>
                {(domains.data ?? []).map((d) => (
                  <option key={d.domain_code} value={d.domain_code}>
                    {d.domain_code} ({d.name})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex-1 space-y-1">
              <span className="text-xs text-muted-foreground">
                Contract (= source contract — 응답 schema 정의)
              </span>
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={contractId ?? ""}
                onChange={(e) =>
                  setContractId(e.target.value ? Number(e.target.value) : null)
                }
                data-testid="select-contract"
              >
                <option value="">— contract 선택 —</option>
                {(contracts.data ?? []).map((c) => (
                  <option key={c.contract_id} value={c.contract_id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="ghost"
              onClick={() => setShowFunctions(true)}
              title="26+ 함수 도움말"
            >
              <Sparkles className="h-4 w-4" />
              함수 도움말
            </Button>
            {contractId && (
              <Button onClick={() => setCreating(true)} data-testid="btn-add-mapping">
                <Plus className="h-4 w-4" />새 매핑 행
              </Button>
            )}
            {contractId && (mappings.data?.length ?? 0) > 0 && (
              <Button
                variant="secondary"
                onClick={() => setDryRunOpen(true)}
                data-testid="btn-dry-run"
              >
                <Code2 className="h-4 w-4" />Dry-run
              </Button>
            )}
          </div>
          {selectedContract && (
            <p className="text-xs text-muted-foreground">
              선택된 contract: <code>{selectedContract.label}</code>
            </p>
          )}
        </CardContent>
      </Card>

      {/* Step 2 — 매핑 목록 */}
      {!contractId ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            먼저 위에서 contract 를 선택하세요. 등록된 contract 가 없다면 Source/API
            Designer 에서 등록 후 contract 가 자동 생성됩니다 (Phase 6 후속에서 자동화).
          </CardContent>
        </Card>
      ) : mappings.isLoading ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">로딩…</CardContent>
        </Card>
      ) : mappings.isError ? (
        <Card>
          <CardContent className="p-6 text-sm text-destructive">
            {(mappings.error as Error).message}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            {(mappings.data?.length ?? 0) === 0 ? (
              <div className="p-6 text-sm text-muted-foreground">
                매핑 행이 없습니다. *새 매핑 행* 버튼으로 시작.
              </div>
            ) : (
              <Table>
                <Thead>
                  <Tr>
                    <Th>#</Th>
                    <Th>source_path</Th>
                    <Th>→ target_table.column</Th>
                    <Th>transform_expr</Th>
                    <Th>required</Th>
                    <Th>상태</Th>
                    <Th>업데이트</Th>
                    <Th>동작</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {mappings.data!.map((m) => (
                    <Tr key={m.mapping_id}>
                      <Td className="text-xs text-muted-foreground">{m.order_no}</Td>
                      <Td>
                        <code className="text-xs">{m.source_path}</code>
                      </Td>
                      <Td>
                        <code className="text-xs">
                          {m.target_table}.{m.target_column}
                        </code>
                        {m.data_type && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            ({m.data_type})
                          </span>
                        )}
                      </Td>
                      <Td>
                        {m.transform_expr ? (
                          <code className="text-xs">{m.transform_expr}</code>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </Td>
                      <Td>
                        {m.is_required ? (
                          <Badge variant="warning">required</Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">opt</span>
                        )}
                      </Td>
                      <Td>
                        <Badge variant={statusVariant(m.status)}>{m.status}</Badge>
                      </Td>
                      <Td className="text-xs text-muted-foreground">
                        {formatDateTime(m.updated_at)}
                      </Td>
                      <Td>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setEditing(m)}
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
      )}

      {creating && contractId && (
        <MappingEditDialog
          mode="create"
          open={creating}
          contractId={contractId}
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <MappingEditDialog
          mode="edit"
          open={!!editing}
          contractId={editing.contract_id}
          existing={editing}
          onClose={() => setEditing(null)}
        />
      )}
      {showFunctions && (
        <FunctionsHelpDialog
          open={showFunctions}
          onClose={() => setShowFunctions(false)}
        />
      )}
      {dryRunOpen && contractId && selectedContract && (
        <DryRunDialog
          open={dryRunOpen}
          contractId={contractId}
          domainCode={selectedContract.domain_code}
          onClose={() => setDryRunOpen(false)}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Edit / Create dialog
// ---------------------------------------------------------------------------
interface MappingEditDialogProps {
  mode: "create" | "edit";
  open: boolean;
  contractId: number;
  existing?: FieldMapping;
  onClose: () => void;
}

function MappingEditDialog({
  mode,
  open,
  contractId,
  existing,
  onClose,
}: MappingEditDialogProps) {
  const create = useCreateMapping();
  const update = useUpdateMapping(existing?.mapping_id ?? 0);
  const transition = useTransitionMapping(existing?.mapping_id ?? 0);
  const remove = useDeleteMapping();

  const [form, setForm] = useState<FieldMappingIn>({
    contract_id: contractId,
    source_path: "",
    target_table: "",
    target_column: "",
    transform_expr: "",
    data_type: "",
    is_required: false,
    order_no: 0,
  });

  useEffect(() => {
    if (mode === "edit" && existing) {
      setForm({
        contract_id: existing.contract_id,
        source_path: existing.source_path,
        target_table: existing.target_table,
        target_column: existing.target_column,
        transform_expr: existing.transform_expr ?? "",
        data_type: existing.data_type ?? "",
        is_required: existing.is_required,
        order_no: existing.order_no,
      });
    } else {
      setForm({
        contract_id: contractId,
        source_path: "",
        target_table: "",
        target_column: "",
        transform_expr: "",
        data_type: "",
        is_required: false,
        order_no: 0,
      });
    }
  }, [mode, existing, contractId]);

  // target table 컬럼 자동 도움말 (선택 — 입력된 target_table 이 있으면 컬럼 dropdown).
  const cols = useTableColumns(form.target_table || null);

  const isReadOnly = mode === "edit" && existing && existing.status !== "DRAFT";

  async function handleSubmit() {
    const payload: FieldMappingIn = {
      ...form,
      transform_expr: form.transform_expr?.trim() || null,
      data_type: form.data_type?.trim() || null,
    };
    try {
      if (mode === "create") {
        await create.mutateAsync(payload);
        toast.success("매핑 행 추가 (DRAFT)");
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

  async function handleTransition(target: MappingStatus) {
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
    if (!confirm(`매핑 행 #${existing.mapping_id} 을 삭제할까요?`)) return;
    try {
      await remove.mutateAsync(existing.mapping_id);
      toast.success("삭제 완료");
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`삭제 실패: ${msg}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? "새 매핑 행"
              : `매핑 #${existing?.mapping_id} (${existing?.status})`}
          </DialogTitle>
        </DialogHeader>

        {isReadOnly && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            DRAFT 만 직접 수정 가능. APPROVED/PUBLISHED 는 새 버전 (Phase 7).
          </div>
        )}

        {/* Phase 8.2 — sample JSON picker (생성 모드 only) */}
        {mode === "create" && !isReadOnly && (
          <JsonPathPicker
            onPick={(path, recommended) => {
              setForm({
                ...form,
                source_path: path,
                transform_expr: recommended ?? form.transform_expr ?? "",
              });
              toast.success(
                recommended
                  ? `source_path = ${path}, 변환 = ${recommended}`
                  : `source_path = ${path}`,
              );
            }}
          />
        )}

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">
              source_path (raw 응답에서의 경로)
            </span>
            <Input
              value={form.source_path}
              onChange={(e) => setForm({ ...form, source_path: e.target.value })}
              placeholder="예: itemname / response.body.items.item.price"
              disabled={isReadOnly}
              data-testid="field-source-path"
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">target_table</span>
            <Input
              value={form.target_table}
              onChange={(e) => setForm({ ...form, target_table: e.target.value })}
              placeholder="예: agri_mart.kamis_price"
              disabled={isReadOnly}
              data-testid="field-target-table"
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">target_column</span>
            {cols.data && cols.data.length > 0 ? (
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={form.target_column}
                onChange={(e) =>
                  setForm({ ...form, target_column: e.target.value })
                }
                disabled={isReadOnly}
                data-testid="field-target-column-select"
              >
                <option value="">— 선택 —</option>
                {cols.data.map((c: TableColumn) => (
                  <option key={c.column_name} value={c.column_name}>
                    {c.column_name} ({c.data_type})
                  </option>
                ))}
              </select>
            ) : (
              <Input
                value={form.target_column}
                onChange={(e) =>
                  setForm({ ...form, target_column: e.target.value })
                }
                placeholder="예: unit_price"
                disabled={isReadOnly}
                data-testid="field-target-column"
              />
            )}
          </label>
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">data_type (선택)</span>
            <Input
              value={form.data_type ?? ""}
              onChange={(e) => setForm({ ...form, data_type: e.target.value })}
              placeholder="예: NUMERIC / TEXT / DATE"
              disabled={isReadOnly}
            />
          </label>
          <label className="col-span-full space-y-1">
            <span className="text-xs text-muted-foreground">
              transform_expr (선택) —{" "}
              <code>text.trim($itemname)</code>{" "}
              <code>number.parse_decimal($price)</code>{" "}
              <code>date.parse($regday)</code> 등 26+ 함수
            </span>
            <Input
              value={form.transform_expr ?? ""}
              onChange={(e) =>
                setForm({ ...form, transform_expr: e.target.value })
              }
              placeholder="예: number.parse_decimal($price)"
              disabled={isReadOnly}
              data-testid="field-transform-expr"
            />
          </label>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_required ?? false}
                onChange={(e) =>
                  setForm({ ...form, is_required: e.target.checked })
                }
                disabled={isReadOnly}
              />
              <span>required</span>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <span className="text-xs text-muted-foreground">order_no</span>
              <Input
                type="number"
                className="w-20"
                value={form.order_no ?? 0}
                onChange={(e) =>
                  setForm({ ...form, order_no: Number(e.target.value) || 0 })
                }
                disabled={isReadOnly}
              />
            </label>
          </div>
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
                  <Button onClick={() => handleTransition("APPROVED")}>승인</Button>
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
                  <Send className="h-4 w-4" /> PUBLISHED
                </Button>
              )}
              {existing.status !== "PUBLISHED" && (
                <Button variant="destructive" onClick={handleDelete}>
                  <Trash2 className="h-4 w-4" />
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
              data-testid="btn-save-mapping"
            >
              {mode === "create" ? "추가" : "저장"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Functions help dialog
// ---------------------------------------------------------------------------
function FunctionsHelpDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const fns = useFunctionRegistry();
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    const list = fns.data ?? [];
    if (!filter.trim()) return list;
    const f = filter.toLowerCase();
    return list.filter(
      (fn: FunctionSpec) =>
        fn.name.toLowerCase().includes(f) ||
        fn.category.toLowerCase().includes(f) ||
        fn.description.toLowerCase().includes(f),
    );
  }, [fns.data, filter]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            transform_expr 함수 도움말 ({fns.data?.length ?? 0} 개)
          </DialogTitle>
        </DialogHeader>
        <Input
          placeholder="검색 — 이름 / 카테고리 / 설명"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          data-testid="filter-functions"
        />
        <p className="text-xs text-muted-foreground">
          사용법: <code>function_name(arg1, arg2, ...)</code>. row 의 컬럼 참조는{" "}
          <code>$column_name</code>. 예: <code>text.trim($itemname)</code>.
        </p>
        <Table>
          <Thead>
            <Tr>
              <Th>name</Th>
              <Th>category</Th>
              <Th>arity</Th>
              <Th>description</Th>
            </Tr>
          </Thead>
          <Tbody>
            {filtered.map((fn: FunctionSpec) => (
              <Tr key={fn.name}>
                <Td>
                  <code className="text-xs">{fn.name}</code>
                </Td>
                <Td>
                  <Badge variant="muted">{fn.category}</Badge>
                </Td>
                <Td className="text-xs text-muted-foreground">
                  {fn.arity_min}
                  {fn.arity_max == null
                    ? "+"
                    : fn.arity_max > fn.arity_min
                      ? `–${fn.arity_max}`
                      : ""}
                </Td>
                <Td className="text-xs">{fn.description}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Dry-run dialog
// ---------------------------------------------------------------------------
function DryRunDialog({
  open,
  contractId,
  domainCode,
  onClose,
}: {
  open: boolean;
  contractId: number;
  domainCode: string;
  onClose: () => void;
}) {
  const dryRun = useDryRunFieldMapping();
  const [sourceTable, setSourceTable] = useState("");
  const [targetTable, setTargetTable] = useState("");
  const [applyOnlyPublished, setApplyOnlyPublished] = useState(false);

  async function handleRun() {
    if (!sourceTable.trim()) {
      toast.error("source_table 입력 필요 (예: stg.daily_apples)");
      return;
    }
    try {
      const result = await dryRun.mutateAsync({
        domain_code: domainCode,
        contract_id: contractId,
        source_table: sourceTable.trim(),
        target_table: targetTable.trim() || undefined,
        apply_only_published: applyOnlyPublished,
      });
      if (result.errors.length > 0) {
        toast.error(`Dry-run 실패: ${result.errors.join("; ")}`);
      } else {
        toast.success(
          `Dry-run 완료 — ${result.row_counts[0] ?? 0}건 / ${result.duration_ms}ms (rollback)`,
        );
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`호출 실패: ${msg}`);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>매핑 Dry-run (트랜잭션 rollback 보장)</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">
          contract #{contractId} ({domainCode}) 의 매핑들을 *실 mart 적재 없이* 검증.
          source_table 의 row 를 매핑 적용 → sandbox 결과 row_count 만 표시.
        </p>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">source_table</span>
            <Input
              value={sourceTable}
              onChange={(e) => setSourceTable(e.target.value)}
              placeholder="예: stg.daily_apples / wf.tmp_run_42_kamis_pubapi"
              data-testid="dryrun-source-table"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs text-muted-foreground">
              target_table override (선택 — 비우면 매핑의 target_table 사용)
            </span>
            <Input
              value={targetTable}
              onChange={(e) => setTargetTable(e.target.value)}
              placeholder="비워두면 매핑 row 의 target_table 자동"
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={applyOnlyPublished}
              onChange={(e) => setApplyOnlyPublished(e.target.checked)}
            />
            <span>PUBLISHED 매핑만 적용 (DRAFT 무시)</span>
          </label>
          {dryRun.data && (
            <pre className="overflow-x-auto rounded-md border border-border bg-muted/40 p-3 text-xs">
              {JSON.stringify(dryRun.data, null, 2)}
            </pre>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            닫기
          </Button>
          <Button
            onClick={handleRun}
            disabled={dryRun.isPending}
            data-testid="btn-execute-dryrun"
          >
            {dryRun.isPending ? "실행 중…" : "Dry-run 실행"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
