// Phase 8.2 — ETL Canvas 실행 준비 체크리스트.
//
// 사용자가 노드를 다 그렸지만 자산을 안 골랐거나 화살표가 빠진 경우 즉시 보임.
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

// 자산 dropdown 이 필요한 노드 → required config_json key
const ASSET_REQUIRED: Partial<Record<NodeType, string[]>> = {
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

export function CanvasReadinessChecklist({
  nodes,
  edges,
}: CanvasReadinessChecklistProps) {
  if (nodes.length === 0) return null;

  const checks: CheckItem[] = [];

  // 1. Source 박스 1개 이상
  const sourceCount = nodes.filter((n) =>
    SOURCE_TYPES.includes(n.data.node_type),
  ).length;
  checks.push({
    ok: sourceCount > 0,
    label: "데이터 수집 박스 1개 이상",
    detail:
      sourceCount > 0
        ? `${sourceCount}개 (DATA SOURCES 카테고리)`
        : "PUBLIC_API_FETCH / WEBHOOK_INGEST 등 추가 필요",
  });

  // 2. Load 박스 1개 이상
  const loadCount = nodes.filter((n) => LOAD_TYPES.includes(n.data.node_type))
    .length;
  checks.push({
    ok: loadCount > 0,
    label: "마트 적재 박스 1개 이상",
    detail:
      loadCount > 0
        ? `${loadCount}개`
        : "LOAD_TARGET 박스 추가 필요 (없으면 데이터가 어디로 가는지 불명)",
  });

  // 3. 모든 박스에 자산 dropdown 선택됨
  const missingAssets: string[] = [];
  for (const n of nodes) {
    const required = ASSET_REQUIRED[n.data.node_type];
    if (!required) continue;
    const cfg = n.data.config_json as Record<string, unknown>;
    for (const k of required) {
      if (cfg[k] === undefined || cfg[k] === null || cfg[k] === "") {
        missingAssets.push(`${n.data.node_key}.${k}`);
      }
    }
  }
  checks.push({
    ok: missingAssets.length === 0,
    label: "모든 박스의 자산 dropdown 선택됨",
    detail:
      missingAssets.length === 0
        ? `${nodes.length}개 박스 OK`
        : `누락 ${missingAssets.length}건: ${missingAssets.slice(0, 3).join(", ")}${missingAssets.length > 3 ? "..." : ""}`,
  });

  // 4. 모든 박스가 화살표로 연결됨 (고립 박스 0)
  const connectedSet = new Set<string>();
  for (const e of edges) {
    if (e.source) connectedSet.add(e.source);
    if (e.target) connectedSet.add(e.target);
  }
  const orphans = nodes.filter((n) => !connectedSet.has(n.id));
  // 단일 박스 워크플로는 OK — 박스 ≥ 2 일 때만 검사
  checks.push({
    ok: nodes.length < 2 || orphans.length === 0,
    label: "박스가 화살표로 연결됨",
    detail:
      orphans.length === 0
        ? `${edges.length}개 edge`
        : `고립 ${orphans.length}개: ${orphans.map((o) => o.data.node_key).slice(0, 3).join(", ")}`,
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
              <span className="text-amber-700">실행 준비 미완료</span>
            </>
          )}
          <span className="text-muted-foreground">
            ({checks.filter((c) => c.ok).length} / {checks.length} 충족)
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
                <div
                  className={cn(
                    "font-medium",
                    c.ok ? "text-green-700" : "text-amber-700",
                  )}
                >
                  {c.label}
                </div>
                {c.detail && (
                  <div className="text-[10px] text-muted-foreground">
                    {c.detail}
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
