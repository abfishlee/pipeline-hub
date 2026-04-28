import {
  Bell,
  Code2,
  Database,
  DatabaseZap,
  FileText,
  Globe,
  HardDrive,
  Hash,
  Image,
  Inbox,
  Network,
  Repeat,
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
        type: "PUBLIC_API_FETCH",
        label: "API Pull",
        description: "등록된 API connector에서 데이터를 가져옵니다.",
        icon: Globe,
      },
      {
        type: "WEBHOOK_INGEST",
        label: "Inbound Push",
        description: "외부에서 push된 webhook 데이터를 읽습니다.",
        icon: Inbox,
      },
      {
        type: "FILE_UPLOAD_INGEST",
        label: "File Upload",
        description: "업로드된 파일 payload를 읽습니다.",
        icon: Upload,
      },
      {
        type: "OCR_RESULT_INGEST",
        label: "OCR Result",
        description: "외부 OCR 시스템이 push한 결과를 읽습니다.",
        icon: FileText,
      },
      {
        type: "CRAWLER_RESULT_INGEST",
        label: "Crawler Result",
        description: "외부 crawler 시스템이 push한 결과를 읽습니다.",
        icon: Network,
      },
      {
        type: "DB_INCREMENTAL_FETCH",
        label: "DB Incremental",
        description: "watermark 기준으로 원천 DB에서 증분 수집합니다.",
        icon: DatabaseZap,
      },
      {
        type: "OCR_TRANSFORM",
        label: "OCR Transform",
        description: "이미지를 OCR 텍스트/필드로 변환합니다.",
        icon: Image,
      },
      {
        type: "CRAWL_FETCH",
        label: "Crawl Fetch",
        description: "웹 페이지에서 원천 데이터를 수집합니다.",
        icon: Network,
      },
      {
        type: "CDC_EVENT_FETCH",
        label: "CDC Event",
        description: "DB logical replication stream. Phase 9 stub.",
        icon: Repeat,
        stub: true,
      },
      {
        type: "SOURCE_DATA",
        label: "Legacy Source",
        description: "기존 raw/source 데이터를 읽습니다.",
        icon: Database,
      },
    ],
  },
  {
    label: "2. Prepare",
    entries: [
      {
        type: "MAP_FIELDS",
        label: "Field Mapping",
        description: "JSONB/source payload를 flat staging 컬럼으로 꺼냅니다.",
        icon: Wand2,
      },
    ],
  },
  {
    label: "3. SQL Studio",
    entries: [
      {
        type: "SQL_ASSET_TRANSFORM",
        label: "SQL Asset",
        description: "SQL Studio 자산을 실행합니다. Transform/표준화/품질검사/함수 등록을 모두 포함합니다.",
        icon: Code2,
      },
      {
        type: "SQL_INLINE_TRANSFORM",
        label: "SQL Inline",
        description: "Canvas에서 임시 SQL을 직접 작성해 실행합니다.",
        icon: Code2,
      },
    ],
  },
  {
    label: "4. Load / Output",
    entries: [
      {
        type: "LOAD_TARGET",
        label: "Load Target",
        description: "Load Policy에 따라 staging/mart에 적재합니다.",
        icon: HardDrive,
      },
      {
        type: "NOTIFY",
        label: "Notify",
        description: "Slack, Email, Webhook으로 실행 결과를 알립니다.",
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
    <aside className="flex w-64 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border bg-background p-3">
      <div className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase text-muted-foreground">
        <Hash className="h-3 w-3" />
        Canvas modules
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
                title="Drag or double-click to add this node."
              >
                <div className="flex items-start gap-2 p-2 text-xs">
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1">
                      <span className="font-mono text-[11px] font-semibold">{p.label}</span>
                      {p.stub && (
                        <span className="rounded bg-amber-100 px-1 text-[9px] font-semibold text-amber-700">
                          STUB
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] leading-4 text-muted-foreground">
                      {p.description}
                    </div>
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
