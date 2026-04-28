import { ArrowRight, Check, Database, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useDomains } from "@/api/v2/domains";
import {
  type FieldMappingIn,
  type MappingSource,
  useCreateMapping,
  useMappings,
  useMappingSources,
} from "@/api/v2/mappings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

type SourceType = "api" | "inbound";

interface SourceField {
  path: string;
  label: string;
  value: unknown;
  scope: "root" | "item";
}

interface TargetField {
  column: string;
  label: string;
  required: boolean;
  dataType: string;
  aliases: string[];
}

interface DraftMapping {
  sourcePath: string;
  targetColumn: string;
  confidence: number;
  reason: string;
  dataType: string;
  required: boolean;
}

const TARGET_TABLE = "agri_price_stg.inbound_price_events";

const TARGET_FIELDS: TargetField[] = [
  {
    column: "source_event_id",
    label: "원천 이벤트 ID",
    required: true,
    dataType: "TEXT",
    aliases: ["event_id", "eventid", "source_event_id", "idempotency_key"],
  },
  {
    column: "provider_code",
    label: "제공자 코드",
    required: true,
    dataType: "TEXT",
    aliases: ["vendor_code", "provider_code", "source_code", "vendor"],
  },
  {
    column: "captured_at",
    label: "수집/촬영 시각",
    required: true,
    dataType: "TIMESTAMPTZ",
    aliases: ["captured_at", "collected_at", "timestamp", "received_at"],
  },
  {
    column: "document_id",
    label: "문서/OCR ID",
    required: false,
    dataType: "TEXT",
    aliases: ["document_id", "doc_id", "receipt_id", "image_id"],
  },
  {
    column: "source_product_id",
    label: "원천 상품 ID",
    required: false,
    dataType: "TEXT",
    aliases: ["source_product_id", "product_id", "item_id", "sku"],
  },
  {
    column: "product_name",
    label: "상품명",
    required: true,
    dataType: "TEXT",
    aliases: ["product_name", "item_name", "product", "item", "상품명", "품목명"],
  },
  {
    column: "price",
    label: "가격",
    required: true,
    dataType: "NUMERIC",
    aliases: ["price", "amount", "sale_price", "unit_price", "가격"],
  },
  {
    column: "unit",
    label: "단위",
    required: false,
    dataType: "TEXT",
    aliases: ["unit", "uom", "규격", "단위"],
  },
  {
    column: "store_name",
    label: "매장명",
    required: false,
    dataType: "TEXT",
    aliases: ["store_name", "store", "shop_name", "market_name", "매장명"],
  },
  {
    column: "confidence",
    label: "신뢰도",
    required: false,
    dataType: "NUMERIC",
    aliases: ["confidence", "ocr_confidence", "score", "신뢰도"],
  },
  {
    column: "bbox",
    label: "OCR 좌표",
    required: false,
    dataType: "JSONB",
    aliases: ["bbox", "bounding_box", "box"],
  },
];

export function FieldMappingDesigner() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("agri_price");
  const [sourceType, setSourceType] = useState<SourceType>("inbound");
  const sources = useMappingSources({ domain_code: domainCode, source_type: sourceType });
  const [selectedSourceId, setSelectedSourceId] = useState("");
  const selectedSource = useMemo(
    () => sources.data?.find((s) => s.source_id === selectedSourceId) ?? null,
    [sources.data, selectedSourceId],
  );
  const mappings = useMappings({
    contract_id: selectedSource?.contract_id,
  });
  const createMapping = useCreateMapping();
  const sourceFields = useMemo(
    () => (selectedSource ? extractSourceFields(selectedSource) : []),
    [selectedSource],
  );
  const [drafts, setDrafts] = useState<DraftMapping[]>([]);

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
    setDrafts(autoMap(sourceFields));
  }, [selectedSource, sourceFields]);

  const previewRows = useMemo(
    () => (selectedSource ? buildPreview(selectedSource.sample_payload, drafts, selectedSource.item_path) : []),
    [selectedSource, drafts],
  );

  async function saveDrafts() {
    if (!selectedSource) return;
    const existingKeys = new Set(
      (mappings.data ?? []).map((m) => `${m.target_table}.${m.target_column}`),
    );
    const rows: FieldMappingIn[] = drafts
      .filter((d) => d.targetColumn)
      .filter((d) => !existingKeys.has(`${TARGET_TABLE}.${d.targetColumn}`))
      .map((d, idx) => ({
        contract_id: selectedSource.contract_id,
        source_path: d.sourcePath,
        target_table: TARGET_TABLE,
        target_column: d.targetColumn,
        data_type: d.dataType,
        is_required: d.required,
        order_no: idx + 1,
        transform_expr: recommendedTransform(d),
      }));
    if (rows.length === 0) {
      toast.info("저장할 신규 매핑이 없습니다");
      return;
    }
    try {
      for (const row of rows) {
        await createMapping.mutateAsync(row);
      }
      toast.success(`자동 매핑 ${rows.length}건을 저장했습니다`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "매핑 저장 실패");
    }
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Field Mapping</h2>
        <p className="max-w-4xl text-sm text-muted-foreground">
          API Pull과 Inbound Push의 sample/contract에서 source field를 자동 추출하고,
          agri_price 표준 target field로 매핑을 추천합니다.
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
              <option value="">선택</option>
              {(sources.data ?? []).map((s) => (
                <option key={s.source_id} value={s.source_id}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
        </CardContent>
      </Card>

      {selectedSource && (
        <div className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
          <Card>
            <CardContent className="space-y-3 p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-semibold">{selectedSource.label}</div>
                  <div className="text-xs text-muted-foreground">
                    contract #{selectedSource.contract_id} · item path{" "}
                    <code>{selectedSource.item_path ?? "(root)"}</code> · target{" "}
                    <code>{TARGET_TABLE}</code>
                  </div>
                </div>
                <Button onClick={() => setDrafts(autoMap(sourceFields))} variant="outline">
                  <RefreshCw className="h-4 w-4" />
                  Auto Map
                </Button>
              </div>

              <Table>
                <Thead>
                  <Tr>
                    <Th>Source Field</Th>
                    <Th></Th>
                    <Th>Target Field</Th>
                    <Th>Confidence</Th>
                    <Th>Reason</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {sourceFields.map((field) => {
                    const draft = drafts.find((d) => d.sourcePath === field.path);
                    return (
                      <Tr key={field.path}>
                        <Td>
                          <code className="text-xs">{field.path}</code>
                          <div className="text-xs text-muted-foreground">
                            {field.scope} · {typeof field.value}
                          </div>
                        </Td>
                        <Td>
                          <ArrowRight className="h-4 w-4 text-muted-foreground" />
                        </Td>
                        <Td>
                          <select
                            className="h-8 w-full rounded-md border bg-background px-2 text-sm"
                            value={draft?.targetColumn ?? ""}
                            onChange={(e) =>
                              setDrafts((prev) =>
                                upsertDraft(prev, field, e.target.value),
                              )
                            }
                          >
                            <option value="">매핑 안 함</option>
                            {TARGET_FIELDS.map((t) => (
                              <option key={t.column} value={t.column}>
                                {t.column} {t.required ? "*" : ""}
                              </option>
                            ))}
                          </select>
                        </Td>
                        <Td>
                          {draft?.targetColumn ? (
                            <ConfidenceBadge score={draft.confidence} />
                          ) : (
                            <span className="text-xs text-muted-foreground">-</span>
                          )}
                        </Td>
                        <Td className="text-xs text-muted-foreground">
                          {draft?.reason ?? "-"}
                        </Td>
                      </Tr>
                    );
                  })}
                </Tbody>
              </Table>

              <div className="flex justify-end">
                <Button onClick={saveDrafts} disabled={createMapping.isPending}>
                  <Check className="h-4 w-4" />
                  추천 매핑 저장
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
                  <div className="text-sm text-muted-foreground">
                    아직 저장된 매핑이 없습니다.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {mappings.data?.map((m) => (
                      <div key={m.mapping_id} className="rounded-md border p-2 text-xs">
                        <code>{m.source_path}</code>
                        <span className="mx-2 text-muted-foreground">→</span>
                        <code>
                          {m.target_table}.{m.target_column}
                        </code>
                        <div className="mt-1 flex items-center gap-2 text-muted-foreground">
                          <Badge variant="muted">{m.status}</Badge>
                          {formatDateTime(m.updated_at)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function extractSourceFields(source: MappingSource): SourceField[] {
  const sample = source.sample_payload ?? {};
  const itemPath = source.item_path ?? "items";
  const fields: SourceField[] = [];
  if (isRecord(sample)) {
    for (const [key, value] of Object.entries(sample)) {
      if (key === itemPath && Array.isArray(value)) continue;
      fields.push({ path: key, label: key, value, scope: "root" });
    }
    const items = sample[itemPath];
    if (Array.isArray(items) && items.length > 0 && isRecord(items[0])) {
      for (const [key, value] of Object.entries(items[0])) {
        fields.push({
          path: `${itemPath}[].${key}`,
          label: key,
          value,
          scope: "item",
        });
      }
    }
  }
  return fields;
}

function autoMap(fields: SourceField[]): DraftMapping[] {
  const used = new Set<string>();
  const drafts: DraftMapping[] = [];
  for (const field of fields) {
    const match = bestTarget(field, used);
    if (!match) continue;
    used.add(match.target.column);
    drafts.push({
      sourcePath: field.path,
      targetColumn: match.target.column,
      confidence: match.score,
      reason: match.reason,
      dataType: match.target.dataType,
      required: match.target.required,
    });
  }
  return drafts;
}

function bestTarget(field: SourceField, used: Set<string>) {
  const normalized = normalize(field.label);
  let best: { target: TargetField; score: number; reason: string } | null = null;
  for (const target of TARGET_FIELDS) {
    if (used.has(target.column)) continue;
    let score = 0;
    let reason = "";
    if (normalize(target.column) === normalized) {
      score = 99;
      reason = "exact column match";
    } else if (target.aliases.map(normalize).includes(normalized)) {
      score = 94;
      reason = "alias match";
    } else if (normalize(target.column).includes(normalized) || normalized.includes(normalize(target.column))) {
      score = 75;
      reason = "name similarity";
    } else if (target.dataType === "NUMERIC" && typeof field.value === "number") {
      score = 55;
      reason = "numeric type hint";
    }
    if (score > 0 && (!best || score > best.score)) best = { target, score, reason };
  }
  return best && best.score >= 55 ? best : null;
}

function upsertDraft(
  drafts: DraftMapping[],
  field: SourceField,
  targetColumn: string,
): DraftMapping[] {
  const target = TARGET_FIELDS.find((t) => t.column === targetColumn);
  const next = drafts.filter((d) => d.sourcePath !== field.path);
  if (!target) return next;
  return [
    ...next,
    {
      sourcePath: field.path,
      targetColumn,
      confidence: 100,
      reason: "manual selection",
      dataType: target.dataType,
      required: target.required,
    },
  ];
}

function buildPreview(
  sample: Record<string, unknown>,
  drafts: DraftMapping[],
  itemPath: string | null,
) {
  const rows = Array.isArray(sample[itemPath ?? "items"])
    ? (sample[itemPath ?? "items"] as unknown[])
    : [sample];
  return rows.slice(0, 3).map((item) => {
    const out: Record<string, unknown> = {};
    for (const draft of drafts) {
      if (!draft.targetColumn) continue;
      out[draft.targetColumn] = valueAt(sample, item, draft.sourcePath, itemPath ?? "items");
    }
    return out;
  });
}

function valueAt(
  root: Record<string, unknown>,
  item: unknown,
  path: string,
  itemPath: string,
) {
  if (path.startsWith(`${itemPath}[].`)) {
    const key = path.slice(`${itemPath}[].`.length);
    return isRecord(item) ? item[key] : undefined;
  }
  return root[path];
}

function recommendedTransform(draft: DraftMapping): string | null {
  if (draft.dataType === "NUMERIC") return `number.parse_decimal($${lastPath(draft.sourcePath)})`;
  if (draft.dataType === "TIMESTAMPTZ") return `date.parse($${lastPath(draft.sourcePath)})`;
  if (draft.dataType === "TEXT") return `text.trim($${lastPath(draft.sourcePath)})`;
  return null;
}

function lastPath(path: string) {
  return path.split(".").pop()?.replace("[]", "") ?? path;
}

function normalize(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9가-힣]/g, "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function ConfidenceBadge({ score }: { score: number }) {
  const variant = score >= 90 ? "success" : score >= 70 ? "warning" : "muted";
  return <Badge variant={variant}>{score}%</Badge>;
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
