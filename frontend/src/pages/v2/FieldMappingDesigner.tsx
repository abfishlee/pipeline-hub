import { ArrowRight, Check, Database, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { useDomains } from "@/api/v2/domains";
import {
  type FieldMapping,
  type FieldMappingIn,
  type FunctionSpec,
  type MappingSource,
  useCreateMapping,
  useFunctionRegistry,
  useMappings,
  useMappingSources,
  useUpdateMappingById,
} from "@/api/v2/mappings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

type SourceType = "api" | "inbound";
type FieldType = "varchar" | "date" | "number" | "long" | "boolean" | "jsonb";

interface SourceField {
  path: string;
  key: string;
  value: unknown;
  scope: "root" | "item";
}

interface DraftMapping {
  sourcePath: string;
  sourceKey: string;
  targetColumn: string;
  dataType: FieldType;
  transformExpr: string;
  mapped: boolean;
  confidence: number;
  reason: string;
  scopeLabel: string;
}

const DATA_TYPES: FieldType[] = ["varchar", "date", "number", "long", "boolean", "jsonb"];

export function FieldMappingDesigner() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("agri_price");
  const [sourceType, setSourceType] = useState<SourceType>("inbound");
  const sources = useMappingSources({ domain_code: domainCode, source_type: sourceType });
  const functions = useFunctionRegistry();
  const [selectedSourceId, setSelectedSourceId] = useState("");

  const selectedSource = useMemo(
    () => sources.data?.find((s) => s.source_id === selectedSourceId) ?? null,
    [sources.data, selectedSourceId],
  );
  const mappings = useMappings({ contract_id: selectedSource?.contract_id });
  const createMapping = useCreateMapping();
  const updateMapping = useUpdateMappingById();
  const [drafts, setDrafts] = useState<DraftMapping[]>([]);
  const targetTable = useMemo(
    () => (selectedSource ? defaultTargetTable(selectedSource) : `${domainCode}_stg.source_flat`),
    [domainCode, selectedSource],
  );

  const sourceFields = useMemo(
    () => (selectedSource ? extractSourceFields(selectedSource) : []),
    [selectedSource],
  );
  const previewRows = useMemo(
    () => (selectedSource ? buildPreview(selectedSource.sample_payload, drafts, selectedSource.item_path) : []),
    [selectedSource, drafts],
  );

  useEffect(() => {
    if (!selectedSourceId && sources.data?.length) {
      setSelectedSourceId(sources.data[0].source_id);
    }
  }, [selectedSourceId, sources.data]);

  useEffect(() => {
    if (!selectedSource) {
      setDrafts([]);
      return;
    }
    setDrafts(autoMap(sourceFields, mappings.data ?? []));
  }, [selectedSource, sourceFields, mappings.data]);

  async function saveDrafts() {
    if (!selectedSource) return;
    const rows = drafts.filter((d) => d.mapped && d.targetColumn.trim());
    if (rows.length === 0) {
      toast.info("저장할 매핑이 없습니다.");
      return;
    }

    const existingBySourcePath = new Map(
      (mappings.data ?? []).map((m) => [m.source_path, m]),
    );
    try {
      let created = 0;
      let updated = 0;
      for (const [idx, draft] of rows.entries()) {
        const body: FieldMappingIn = {
          contract_id: selectedSource.contract_id,
          source_path: draft.sourcePath,
          target_table: targetTable,
          target_column: normalizeColumn(draft.targetColumn),
          data_type: draft.dataType,
          is_required: false,
          order_no: idx + 1,
          transform_expr: draft.transformExpr.trim() || null,
        };
        const existing = existingBySourcePath.get(draft.sourcePath);
        if (existing) {
          await updateMapping.mutateAsync({ mappingId: existing.mapping_id, body });
          updated += 1;
        } else {
          await createMapping.mutateAsync(body);
          created += 1;
        }
      }
      toast.success(`저장 완료: 신규 ${created}건, 수정 ${updated}건`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "매핑 저장 실패");
    }
  }

  const busy = createMapping.isPending || updateMapping.isPending;

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Field Mapping</h2>
        <p className="max-w-4xl text-sm text-muted-foreground">
          API Pull 또는 Inbound Push의 JSONB payload에서 필드를 꺼내 평탄화 컬럼을 정의합니다.
          Auto Map은 JSON key를 target field로 채우고 값 샘플을 보고 타입을 추정합니다.
        </p>
      </div>

      <Card>
        <CardContent className="grid gap-3 p-4 lg:grid-cols-[180px_180px_1fr]">
          <Field label="도메인">
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
              value={domainCode}
              onChange={(e) => {
                setDomainCode(e.target.value);
                setSelectedSourceId("");
              }}
            >
              {(domains.data ?? []).map((d) => (
                <option key={d.domain_code} value={d.domain_code}>
                  {d.domain_code}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Source Type">
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
              value={sourceType}
              onChange={(e) => {
                setSourceType(e.target.value as SourceType);
                setSelectedSourceId("");
              }}
            >
              <option value="inbound">Inbound Push</option>
              <option value="api">API Pull</option>
            </select>
          </Field>
          <Field label="Mapping Source">
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
              value={selectedSourceId}
              onChange={(e) => setSelectedSourceId(e.target.value)}
            >
              <option value="">소스 선택</option>
              {(sources.data ?? []).map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
        </CardContent>
      </Card>

      {selectedSource ? (
        <div className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
          <Card>
            <CardContent className="space-y-3 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-semibold">{selectedSource.label}</div>
                  <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span>contract #{selectedSource.contract_id}</span>
                    <span>item path <code>{selectedSource.item_path ?? "(root)"}</code></span>
                    <span>flat table <code>{targetTable}</code></span>
                  </div>
                </div>
                <Button onClick={() => setDrafts(autoMap(sourceFields, mappings.data ?? []))} variant="outline">
                  <RefreshCw className="h-4 w-4" />
                  Auto Map
                </Button>
              </div>

              <Table>
                <Thead>
                  <Tr>
                    <Th className="w-[28%]">JSONB Source Key</Th>
                    <Th className="w-8"></Th>
                    <Th>Target Field</Th>
                    <Th className="w-[130px]">Type</Th>
                    <Th className="w-[210px]">Function</Th>
                    <Th className="w-[90px]">Use</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {drafts.map((draft) => (
                    <Tr key={draft.sourcePath}>
                      <Td>
                        <code className="text-xs">{draft.sourcePath}</code>
                        <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{draft.scopeLabel}</span>
                          <ConfidenceBadge score={draft.confidence} />
                        </div>
                      </Td>
                      <Td>
                        <ArrowRight className="h-4 w-4 text-muted-foreground" />
                      </Td>
                      <Td>
                        <input
                          className="h-8 w-full rounded-md border bg-background px-2 text-sm"
                          value={draft.targetColumn}
                          disabled={!draft.mapped}
                          onChange={(e) => updateDraft(draft.sourcePath, { targetColumn: e.target.value })}
                        />
                        <div className="mt-1 truncate text-xs text-muted-foreground">{draft.reason}</div>
                      </Td>
                      <Td>
                        <select
                          className="h-8 w-full rounded-md border bg-background px-2 text-sm"
                          value={draft.dataType}
                          disabled={!draft.mapped}
                          onChange={(e) => updateDraft(draft.sourcePath, { dataType: e.target.value as FieldType })}
                        >
                          {DATA_TYPES.map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                      </Td>
                      <Td>
                        <FunctionPicker
                          value={draft.transformExpr}
                          disabled={!draft.mapped}
                          fieldPath={draft.sourcePath}
                          dataType={draft.dataType}
                          functions={functions.data ?? []}
                          onChange={(value) => updateDraft(draft.sourcePath, { transformExpr: value })}
                        />
                      </Td>
                      <Td>
                        <label className="inline-flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={draft.mapped}
                            onChange={(e) => updateDraft(draft.sourcePath, { mapped: e.target.checked })}
                          />
                          매핑
                        </label>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>

              {drafts.length === 0 && (
                <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
                  선택한 소스의 sample payload에서 추출할 필드를 찾지 못했습니다.
                </div>
              )}

              <div className="flex justify-end">
                <Button onClick={saveDrafts} disabled={busy || drafts.length === 0}>
                  <Check className="h-4 w-4" />
                  저장
                </Button>
              </div>
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardContent className="space-y-3 p-4">
                <div className="flex items-center gap-2 font-semibold">
                  <Sparkles className="h-4 w-4 text-primary" />
                  Sample Preview
                </div>
                <pre className="max-h-80 overflow-auto rounded-md bg-muted/40 p-3 text-xs">
                  {JSON.stringify(previewRows, null, 2)}
                </pre>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="space-y-3 p-4">
                <div className="flex items-center gap-2 font-semibold">
                  <Database className="h-4 w-4 text-primary" />
                  Existing Mappings
                </div>
                {(mappings.data?.length ?? 0) === 0 ? (
                  <div className="text-sm text-muted-foreground">아직 저장된 매핑이 없습니다.</div>
                ) : (
                  <div className="space-y-2">
                    {mappings.data?.map((m) => (
                      <div key={m.mapping_id} className="rounded-md border p-2 text-xs">
                        <div className="flex items-center gap-2">
                          <code className="truncate">{m.source_path}</code>
                          <span className="text-muted-foreground">→</span>
                          <code className="font-semibold">{m.target_column}</code>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-muted-foreground">
                          <Badge variant="muted">{m.status}</Badge>
                          <span>{m.data_type ?? "-"}</span>
                          <span>{formatDateTime(m.updated_at)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            매핑할 Source를 선택하세요. API Pull과 Inbound Push는 서로 분리해서 조회됩니다.
          </CardContent>
        </Card>
      )}
    </div>
  );

  function updateDraft(sourcePath: string, patch: Partial<DraftMapping>) {
    setDrafts((prev) =>
      prev.map((d) => (d.sourcePath === sourcePath ? { ...d, ...patch } : d)),
    );
  }
}

function extractSourceFields(source: MappingSource): SourceField[] {
  const sample = source.sample_payload ?? {};
  const itemPath = source.item_path || "items";
  const fields: SourceField[] = [];
  if (!isRecord(sample)) return fields;

  for (const [key, value] of Object.entries(sample)) {
    if (key === itemPath && Array.isArray(value)) continue;
    fields.push({ path: key, key, value, scope: "root" });
  }

  const items = sample[itemPath];
  if (Array.isArray(items) && items.length > 0 && isRecord(items[0])) {
    for (const [key, value] of Object.entries(items[0])) {
      fields.push({ path: `${itemPath}[].${key}`, key, value, scope: "item" });
    }
  }
  return fields;
}

function autoMap(fields: SourceField[], existing: FieldMapping[]): DraftMapping[] {
  const existingBySourcePath = new Map(existing.map((m) => [m.source_path, m]));
  return fields.map((field) => {
    const saved = existingBySourcePath.get(field.path);
    const inferredType = inferType(field.value, field.key);
    const sourceKey = lastPath(field.path);
    const targetColumn = saved?.target_column ?? normalizeColumn(sourceKey);
    const dataType = (saved?.data_type?.toLowerCase() as FieldType | undefined) ?? inferredType;
    return {
      sourcePath: field.path,
      sourceKey,
      targetColumn,
      dataType: DATA_TYPES.includes(dataType) ? dataType : inferredType,
      transformExpr: saved?.transform_expr ?? recommendedTransform(inferredType, field.path),
      mapped: true,
      confidence: saved ? 100 : inferConfidence(field.value, inferredType),
      reason: saved ? "기존 저장값을 불러왔습니다." : "JSON key 기반 자동 생성",
      scopeLabel: field.scope === "item" ? "item row" : "root envelope",
    };
  });
}

function inferType(value: unknown, key: string): FieldType {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return Number.isInteger(value) ? "long" : "number";
  if (typeof value === "string") {
    const lowered = key.toLowerCase();
    if (looksLikeDate(value) || lowered.endsWith("_at") || lowered.includes("date")) return "date";
    if (lowered.includes("price") || lowered.includes("amount") || lowered.includes("qty")) return "number";
    return "varchar";
  }
  if (Array.isArray(value) || isRecord(value)) return "jsonb";
  return "varchar";
}

function inferConfidence(value: unknown, dataType: FieldType) {
  if (dataType === "date" && typeof value === "string" && looksLikeDate(value)) return 95;
  if ((dataType === "number" || dataType === "long") && typeof value === "number") return 95;
  if (dataType === "jsonb" && (Array.isArray(value) || isRecord(value))) return 95;
  return 85;
}

function recommendedTransform(dataType: FieldType, sourcePath: string) {
  const varName = `$${lastPath(sourcePath)}`;
  if (dataType === "number") return `number.parse_decimal(${varName})`;
  if (dataType === "long") return `number.parse_decimal(${varName})`;
  if (dataType === "date") return `date.parse(${varName})`;
  if (dataType === "varchar") return `text.trim(${varName})`;
  return "";
}

function buildPreview(
  sample: Record<string, unknown>,
  drafts: DraftMapping[],
  itemPath: string | null,
) {
  const path = itemPath || "items";
  const items = Array.isArray(sample[path]) ? (sample[path] as unknown[]) : [sample];
  return items.slice(0, 3).map((item) => {
    const out: Record<string, unknown> = {};
    for (const draft of drafts) {
      if (!draft.mapped || !draft.targetColumn.trim()) continue;
      out[normalizeColumn(draft.targetColumn)] = valueAt(sample, item, draft.sourcePath, path);
    }
    return out;
  });
}

function valueAt(root: Record<string, unknown>, item: unknown, path: string, itemPath: string) {
  if (path.startsWith(`${itemPath}[].`)) {
    const key = path.slice(`${itemPath}[].`.length);
    return isRecord(item) ? item[key] : undefined;
  }
  return root[path];
}

function FunctionPicker({
  value,
  disabled,
  fieldPath,
  dataType,
  functions,
  onChange,
}: {
  value: string;
  disabled: boolean;
  fieldPath: string;
  dataType: FieldType;
  functions: FunctionSpec[];
  onChange: (value: string) => void;
}) {
  const varName = `$${lastPath(fieldPath)}`;
  const candidates = functionCandidates(dataType, varName, functions);
  return (
    <select
      className="h-8 w-full rounded-md border bg-background px-2 text-sm"
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">함수 없음</option>
      {candidates.map((expr) => (
        <option key={expr} value={expr}>{expr}</option>
      ))}
    </select>
  );
}

function functionCandidates(dataType: FieldType, varName: string, functions: FunctionSpec[]) {
  const names = new Set(functions.map((f) => f.name));
  const wanted =
    dataType === "varchar"
      ? ["text.trim", "text.upper", "text.lower"]
      : dataType === "date"
        ? ["date.parse", "date.to_iso"]
        : dataType === "number" || dataType === "long"
          ? ["number.parse_decimal"]
          : ["json.to_string"];
  return wanted
    .filter((name) => names.size === 0 || names.has(name))
    .map((name) => `${name}(${varName})`);
}

function defaultTargetTable(source: MappingSource) {
  return `${source.domain_code}_stg.${normalizeColumn(source.resource_code)}_flat`;
}

function normalizeColumn(value: string) {
  const snake = value
    .replace(/\[\]/g, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_{2,}/g, "_");
  return snake || "field";
}

function lastPath(path: string) {
  return path.split(".").pop()?.replace("[]", "") ?? path;
}

function looksLikeDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}/.test(value) && !Number.isNaN(Date.parse(value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function ConfidenceBadge({ score }: { score: number }) {
  const variant = score >= 90 ? "success" : score >= 80 ? "warning" : "muted";
  return <Badge variant={variant}>{score}%</Badge>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}
