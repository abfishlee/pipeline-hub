import { AlertCircle, CheckCircle2, Circle } from "lucide-react";
import type { Edge, Node } from "@xyflow/react";
import type { NodeType } from "@/api/pipelines";
import type { DesignerNodeDataV2 } from "@/components/designer/NodeConfigPanelV2";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";

const SOURCE_TYPES: NodeType[] = [
  "SOURCE_DATA",
  "PUBLIC_API_FETCH",
  "WEBHOOK_INGEST",
  "FILE_UPLOAD_INGEST",
  "DB_INCREMENTAL_FETCH",
  "OCR_RESULT_INGEST",
  "CRAWLER_RESULT_INGEST",
  "CDC_EVENT_FETCH",
  "OCR_TRANSFORM",
  "CRAWL_FETCH",
  "SOURCE_API",
];

const LOAD_TYPES: NodeType[] = ["LOAD_TARGET", "LOAD_MASTER", "NOTIFY"];

const REQUIRED_CONFIG: Partial<Record<NodeType, string[]>> = {
  PUBLIC_API_FETCH: ["connector_id"],
  MAP_FIELDS: ["contract_id"],
  SQL_ASSET_TRANSFORM: ["asset_code"],
  HTTP_TRANSFORM: ["provider_code"],
  LOAD_TARGET: ["policy_id"],
  WEBHOOK_INGEST: ["channel_code"],
  FILE_UPLOAD_INGEST: ["channel_code"],
  OCR_RESULT_INGEST: ["channel_code"],
  CRAWLER_RESULT_INGEST: ["channel_code"],
  DB_INCREMENTAL_FETCH: ["source_code"],
  CDC_EVENT_FETCH: ["replication_slot_name"],
};

interface CheckItem {
  ok: boolean;
  label: string;
  detail?: string;
}

interface CanvasReadinessChecklistProps {
  nodes: Node<DesignerNodeDataV2>[];
  edges: Edge[];
}

export function CanvasReadinessChecklist({ nodes, edges }: CanvasReadinessChecklistProps) {
  if (nodes.length === 0) return null;

  const checks: CheckItem[] = [];
  const sourceCount = nodes.filter((n) => SOURCE_TYPES.includes(n.data.node_type)).length;
  checks.push({
    ok: sourceCount > 0,
    label: "수집 또는 입력 노드",
    detail:
      sourceCount > 0
        ? `${sourceCount}개 Source 노드`
        : "API Pull, Inbound Push, OCR Result 같은 Source 노드를 추가하세요.",
  });

  const loadCount = nodes.filter((n) => LOAD_TYPES.includes(n.data.node_type)).length;
  checks.push({
    ok: loadCount > 0,
    label: "마트 적재 또는 출력 노드",
    detail:
      loadCount > 0
        ? `${loadCount}개 Output 노드`
        : "최종 마트까지 검증하려면 Load Target 노드를 연결하세요.",
  });

  const missingAssets: string[] = [];
  for (const n of nodes) {
    const required = REQUIRED_CONFIG[n.data.node_type];
    if (!required) continue;
    const cfg = n.data.config_json as Record<string, unknown>;
    for (const key of required) {
      if (cfg[key] === undefined || cfg[key] === null || cfg[key] === "") {
        missingAssets.push(`${n.data.node_key}.${key}`);
      }
    }
  }
  checks.push({
    ok: missingAssets.length === 0,
    label: "필수 설정",
    detail:
      missingAssets.length === 0
        ? `${nodes.length}개 노드 설정 OK`
        : `누락 ${missingAssets.length}건: ${missingAssets.slice(0, 3).join(", ")}${
            missingAssets.length > 3 ? "..." : ""
          }`,
  });

  const connectedSet = new Set<string>();
  for (const e of edges) {
    if (e.source) connectedSet.add(e.source);
    if (e.target) connectedSet.add(e.target);
  }
  const orphans = nodes.filter((n) => !connectedSet.has(n.id));
  checks.push({
    ok: nodes.length < 2 || orphans.length === 0,
    label: "노드 연결",
    detail:
      orphans.length === 0
        ? `${edges.length}개 edge`
        : `고립 노드 ${orphans.length}개: ${orphans
            .map((o) => o.data.node_key)
            .slice(0, 3)
            .join(", ")}`,
  });

  const modelCount = nodes.filter((n) =>
    ["SQL_INLINE_TRANSFORM", "SQL_ASSET_TRANSFORM", "PYTHON_MODEL_TRANSFORM"].includes(
      n.data.node_type,
    ),
  ).length;
  checks.push({
    ok: modelCount > 0,
    label: "처리 모형",
    detail:
      modelCount > 0
        ? `${modelCount}개 SQL/Python Model 노드`
        : "평탄화 이후 전처리를 검증하려면 SQL Model 또는 Python Model을 추가하세요.",
  });

  const allReady = checks.every((c) => c.ok);

  return (
    <Card
      className={cn(
        "border-2",
        allReady ? "border-green-300 bg-green-50/30" : "border-amber-300 bg-amber-50/30",
      )}
    >
      <CardContent className="p-3 text-xs">
        <div className="mb-2 flex items-center gap-2 font-semibold">
          {allReady ? (
            <>
              <CheckCircle2 className="h-4 w-4 text-green-600" />
              <span className="text-green-700">실행 준비 완료</span>
            </>
          ) : (
            <>
              <AlertCircle className="h-4 w-4 text-amber-600" />
              <span className="text-amber-700">실행 준비 점검 필요</span>
            </>
          )}
          <span className="text-muted-foreground">
            ({checks.filter((c) => c.ok).length} / {checks.length})
          </span>
        </div>
        <ul className="space-y-1">
          {checks.map((c) => (
            <li key={c.label} className="flex items-start gap-1">
              {c.ok ? (
                <CheckCircle2 className="mt-0.5 h-3 w-3 text-green-600" />
              ) : (
                <Circle className="mt-0.5 h-3 w-3 text-amber-600" />
              )}
              <div className="flex-1">
                <div className={cn("font-medium", c.ok ? "text-green-700" : "text-amber-700")}>
                  {c.label}
                </div>
                {c.detail && <div className="text-[10px] text-muted-foreground">{c.detail}</div>}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
