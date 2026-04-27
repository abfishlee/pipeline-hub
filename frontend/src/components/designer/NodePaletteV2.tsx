// Phase 6 Wave 4 — v2 ETL Canvas palette.
// Phase 8.4 — 누락 3종 추가 (OCR_RESULT_INGEST / CRAWLER_RESULT_INGEST / CDC_EVENT_FETCH).
//
// v1 PipelineDesigner 의 NodePalette 와 별개. v2 generic 파이프라인은 자산 박스
// (connector / mapping / sql_asset / load_policy / dq_rule) 를 끌어다 조립.
import {
  Bell,
  Code2,
  Database,
  DatabaseZap,
  FileText,
  Filter,
  FunctionSquare,
  Globe,
  HardDrive,
  Hash,
  Image,
  Inbox,
  Network,
  Repeat,
  ShieldCheck,
  Sigma,
  Sparkles,
  Upload,
  Wand2,
} from "lucide-react";
import type { NodeType } from "@/api/pipelines";
import { Card } from "@/components/ui/card";

interface PaletteEntry {
  type: NodeType;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  // Phase 8.4 — Phase 9 에서 정식 구현될 stub 노드 표기.
  stub?: boolean;
}

interface PaletteCategory {
  label: string;
  entries: PaletteEntry[];
}

// v2 13 종 (Phase 5 generic + Phase 6 PUBLIC_API_FETCH).
const PALETTE: PaletteCategory[] = [
  {
    label: "DATA SOURCES",
    entries: [
      {
        type: "SOURCE_DATA",
        label: "SOURCE_DATA",
        description: "raw_object 또는 polling source 읽기",
        icon: Database,
      },
      {
        type: "PUBLIC_API_FETCH",
        label: "PUBLIC_API_FETCH",
        description: "등록된 OpenAPI connector 호출 (pull)",
        icon: Globe,
      },
      // Phase 7 Wave 1A — 외부 push / upload / DB 수집 3종
      {
        type: "WEBHOOK_INGEST",
        label: "WEBHOOK_INGEST",
        description: "외부 시스템 push 수신 (HMAC + idempotency)",
        icon: Inbox,
      },
      {
        type: "FILE_UPLOAD_INGEST",
        label: "FILE_UPLOAD_INGEST",
        description: "사용자 multipart 업로드 (CSV / JSON)",
        icon: Upload,
      },
      {
        type: "DB_INCREMENTAL_FETCH",
        label: "DB_INCREMENTAL_FETCH",
        description: "외부 DB watermark 기반 incremental",
        icon: DatabaseZap,
      },
      {
        type: "OCR_TRANSFORM",
        label: "OCR_TRANSFORM",
        description: "이미지 → 텍스트 (CLOVA/Upstage)",
        icon: Image,
      },
      {
        type: "CRAWL_FETCH",
        label: "CRAWL_FETCH",
        description: "웹 페이지 크롤링",
        icon: Network,
      },
      // Phase 7 Wave 1B — 외부 OCR/Crawler 업체 push 결과 수신 (Phase 8.4 팔레트 노출)
      {
        type: "OCR_RESULT_INGEST",
        label: "OCR_RESULT_INGEST",
        description: "외부 OCR 업체 결과 push 수신 (텍스트 + 신뢰도)",
        icon: FileText,
      },
      {
        type: "CRAWLER_RESULT_INGEST",
        label: "CRAWLER_RESULT_INGEST",
        description: "외부 Crawler 업체 결과 push 수신 (페이지/상품)",
        icon: Network,
      },
      // Phase 7 Wave 1B — DB CDC stream (Phase 9 정식 구현 예정).
      {
        type: "CDC_EVENT_FETCH",
        label: "CDC_EVENT_FETCH",
        description: "DB logical replication slot stream (Phase 9 stub)",
        icon: Repeat,
        stub: true,
      },
    ],
  },
  {
    label: "TRANSFORM",
    entries: [
      {
        type: "MAP_FIELDS",
        label: "MAP_FIELDS",
        description: "field_mapping 적용 (source → target)",
        icon: Wand2,
      },
      {
        type: "SQL_INLINE_TRANSFORM",
        label: "SQL_INLINE",
        description: "즉석 SQL (즉시 실행, 미저장)",
        icon: Code2,
      },
      {
        type: "SQL_ASSET_TRANSFORM",
        label: "SQL_ASSET",
        description: "등록된 sql_asset (APPROVED/PUBLISHED) 실행",
        icon: Sigma,
      },
      {
        type: "HTTP_TRANSFORM",
        label: "HTTP",
        description: "외부 정제 API 호출 (provider binding)",
        icon: Network,
      },
      {
        type: "FUNCTION_TRANSFORM",
        label: "FUNCTION",
        description: "26+ allowlist 함수 적용",
        icon: FunctionSquare,
      },
      {
        type: "STANDARDIZE",
        label: "STANDARDIZE",
        description: "표준코드 namespace 매칭",
        icon: Sparkles,
      },
    ],
  },
  {
    label: "VALIDATE",
    entries: [
      {
        type: "DEDUP",
        label: "DEDUP",
        description: "key 기준 중복 제거",
        icon: Filter,
      },
      {
        type: "DQ_CHECK",
        label: "DQ_CHECK",
        description: "등록된 dq_rule 평가",
        icon: ShieldCheck,
      },
    ],
  },
  {
    label: "LOAD / OUTPUT",
    entries: [
      {
        type: "LOAD_TARGET",
        label: "LOAD_TARGET",
        description: "load_policy 사용 → mart 적재",
        icon: HardDrive,
      },
      {
        type: "NOTIFY",
        label: "NOTIFY",
        description: "Slack/Email/Webhook",
        icon: Bell,
      },
    ],
  },
];

const DRAG_MIME = "application/x-pipeline-node-type-v2";

interface Props {
  onAdd?: (type: NodeType) => void;
}

export function NodePaletteV2({ onAdd }: Props) {
  const handleDragStart = (event: React.DragEvent, type: NodeType) => {
    event.dataTransfer.setData(DRAG_MIME, type);
    event.dataTransfer.effectAllowed = "move";
  };

  return (
    <aside className="flex w-60 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border bg-background p-3">
      <div className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase text-muted-foreground">
        <Hash className="h-3 w-3" />v2 노드 팔레트
      </div>
      {PALETTE.map((cat) => (
        <div key={cat.label} className="space-y-1">
          <div className="mt-2 px-1 text-[10px] font-semibold uppercase text-muted-foreground">
            {cat.label}
          </div>
          {cat.entries.map((p) => {
            const Icon = p.icon;
            return (
              <Card
                key={p.type}
                draggable
                onDragStart={(e) => handleDragStart(e, p.type)}
                onDoubleClick={() => onAdd?.(p.type)}
                className={`cursor-grab select-none active:cursor-grabbing ${
                  p.stub ? "opacity-60" : ""
                }`}
                title={
                  p.stub
                    ? "Phase 9 정식 구현 예정 — Canvas 배치는 가능하지만 dry-run/실행은 stub 응답"
                    : "드래그하거나 더블클릭으로 추가"
                }
              >
                <div className="flex items-start gap-2 p-2 text-xs">
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div className="flex-1">
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-[11px] font-semibold">
                        {p.label}
                      </span>
                      {p.stub && (
                        <span className="rounded bg-amber-100 px-1 text-[9px] font-semibold text-amber-700">
                          STUB
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] text-muted-foreground">
                      {p.description}
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      ))}
      <p className="mt-2 text-[10px] text-muted-foreground">
        ※ Phase 6 Wave 4 — v2 generic 파이프라인 전용. v1 페이지는{" "}
        <code className="text-[10px]">/pipelines/designer</code>.
      </p>
    </aside>
  );
}

export const NODE_PALETTE_V2_DRAG_MIME = DRAG_MIME;
