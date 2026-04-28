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
  stub?: boolean;
}

interface PaletteCategory {
  label: string;
  entries: PaletteEntry[];
}

const PALETTE: PaletteCategory[] = [
  {
    label: "1. Source",
    entries: [
      {
        type: "SOURCE_DATA",
        label: "SOURCE_DATA",
        description: "기존 raw/source 데이터를 읽습니다.",
        icon: Database,
      },
      {
        type: "PUBLIC_API_FETCH",
        label: "PUBLIC_API_FETCH",
        description: "등록된 API Pull connector를 호출합니다.",
        icon: Globe,
      },
      {
        type: "WEBHOOK_INGEST",
        label: "WEBHOOK_INGEST",
        description: "Inbound Push 이벤트를 읽습니다.",
        icon: Inbox,
      },
      {
        type: "FILE_UPLOAD_INGEST",
        label: "FILE_UPLOAD_INGEST",
        description: "업로드 파일의 payload를 읽습니다.",
        icon: Upload,
      },
      {
        type: "DB_INCREMENTAL_FETCH",
        label: "DB_INCREMENTAL_FETCH",
        description: "외부 DB를 watermark 기준으로 증분 수집합니다.",
        icon: DatabaseZap,
      },
      {
        type: "OCR_TRANSFORM",
        label: "OCR_TRANSFORM",
        description: "이미지를 OCR 텍스트/필드로 변환합니다.",
        icon: Image,
      },
      {
        type: "CRAWL_FETCH",
        label: "CRAWL_FETCH",
        description: "웹 페이지를 크롤링해 원천 데이터를 수집합니다.",
        icon: Network,
      },
      {
        type: "OCR_RESULT_INGEST",
        label: "OCR_RESULT_INGEST",
        description: "외부 OCR 업체가 push한 결과를 읽습니다.",
        icon: FileText,
      },
      {
        type: "CRAWLER_RESULT_INGEST",
        label: "CRAWLER_RESULT_INGEST",
        description: "외부 crawler 업체가 push한 결과를 읽습니다.",
        icon: Network,
      },
      {
        type: "CDC_EVENT_FETCH",
        label: "CDC_EVENT_FETCH",
        description: "DB logical replication stream. Phase 9 stub.",
        icon: Repeat,
        stub: true,
      },
    ],
  },
  {
    label: "2. Prepare",
    entries: [
      {
        type: "MAP_FIELDS",
        label: "MAP_FIELDS",
        description: "JSONB/source fields를 flat columns로 매핑합니다.",
        icon: Wand2,
      },
      {
        type: "SQL_INLINE_TRANSFORM",
        label: "SQL_INLINE",
        description: "일회성 SQL로 값을 변환합니다.",
        icon: Code2,
      },
      {
        type: "SQL_ASSET_TRANSFORM",
        label: "SQL_ASSET",
        description: "등록된 SQL Asset을 실행합니다.",
        icon: Sigma,
      },
      {
        type: "HTTP_TRANSFORM",
        label: "HTTP",
        description: "외부 API로 값을 보강합니다.",
        icon: Network,
      },
      {
        type: "FUNCTION_TRANSFORM",
        label: "FUNCTION",
        description: "허용된 함수를 적용합니다.",
        icon: FunctionSquare,
      },
      {
        type: "STANDARDIZE",
        label: "STANDARDIZE",
        description: "표준코드, 표준명, 표준단위에 매칭합니다.",
        icon: Sparkles,
      },
    ],
  },
  {
    label: "3. Validate",
    entries: [
      {
        type: "DEDUP",
        label: "DEDUP",
        description: "business key 기준으로 중복을 제거합니다.",
        icon: Filter,
      },
      {
        type: "DQ_CHECK",
        label: "DQ_CHECK",
        description: "Quality Rule을 실행하고 실패를 기록합니다.",
        icon: ShieldCheck,
      },
    ],
  },
  {
    label: "4. Load / Output",
    entries: [
      {
        type: "LOAD_TARGET",
        label: "LOAD_TARGET",
        description: "Load Policy에 따라 staging/mart에 적재합니다.",
        icon: HardDrive,
      },
      {
        type: "NOTIFY",
        label: "NOTIFY",
        description: "Slack, Email, Webhook으로 결과를 알립니다.",
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
        <Hash className="h-3 w-3" />
        v2 node palette
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
                    ? "Phase 9 planned node. It can be placed, but execution is not fully implemented yet."
                    : "Drag or double-click to add this node."
                }
              >
                <div className="flex items-start gap-2 p-2 text-xs">
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div className="flex-1">
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-[11px] font-semibold">{p.label}</span>
                      {p.stub && (
                        <span className="rounded bg-amber-100 px-1 text-[9px] font-semibold text-amber-700">
                          STUB
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] text-muted-foreground">{p.description}</div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      ))}
    </aside>
  );
}

export const NODE_PALETTE_V2_DRAG_MIME = DRAG_MIME;
