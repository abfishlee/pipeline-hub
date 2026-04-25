import {
  Bell,
  Database,
  Filter,
  GitMerge,
  Server,
  ShieldCheck,
  Sigma,
} from "lucide-react";
import type { NodeType } from "@/api/pipelines";
import { Card } from "@/components/ui/card";

interface PaletteEntry {
  type: NodeType;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}

const PALETTE: PaletteEntry[] = [
  { type: "NOOP", label: "NOOP", description: "통과 (테스트/플레이스홀더)", icon: GitMerge },
  { type: "SOURCE_API", label: "SOURCE_API", description: "raw_object 에서 최근 N건 읽기", icon: Database },
  { type: "SQL_TRANSFORM", label: "SQL_TRANSFORM", description: "sqlglot 검증 후 sandbox 적재", icon: Sigma },
  { type: "DEDUP", label: "DEDUP", description: "key 기준 중복 제거", icon: Filter },
  { type: "DQ_CHECK", label: "DQ_CHECK", description: "row_count/null/unique 검증", icon: ShieldCheck },
  { type: "LOAD_MASTER", label: "LOAD_MASTER", description: "sandbox → mart UPSERT", icon: Server },
  { type: "NOTIFY", label: "NOTIFY", description: "Slack/Email/Webhook (Phase 4 발송)", icon: Bell },
];

const DRAG_MIME = "application/x-pipeline-node-type";

interface Props {
  onAdd?: (type: NodeType) => void;
}

export function NodePalette({ onAdd }: Props) {
  const handleDragStart = (event: React.DragEvent, type: NodeType) => {
    event.dataTransfer.setData(DRAG_MIME, type);
    event.dataTransfer.effectAllowed = "move";
  };

  return (
    <aside className="flex w-60 shrink-0 flex-col gap-2 overflow-y-auto border-r border-border bg-background p-3">
      <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">
        노드 팔레트
      </div>
      {PALETTE.map((p) => {
        const Icon = p.icon;
        return (
          <Card
            key={p.type}
            draggable
            onDragStart={(e) => handleDragStart(e, p.type)}
            onDoubleClick={() => onAdd?.(p.type)}
            className="cursor-grab select-none active:cursor-grabbing"
            title="드래그하거나 더블클릭으로 추가"
          >
            <div className="flex items-start gap-2 p-3 text-xs">
              <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div className="flex-1">
                <div className="font-mono font-semibold">{p.label}</div>
                <div className="text-[10px] text-muted-foreground">
                  {p.description}
                </div>
              </div>
            </div>
          </Card>
        );
      })}
      <p className="mt-2 text-[10px] text-muted-foreground">
        ※ Phase 3.2.4 한정 — 7종. 추가 노드(SOURCE_DB / OCR / CRAWLER /
        HUMAN_REVIEW) 는 Phase 4.
      </p>
    </aside>
  );
}

export const NODE_PALETTE_DRAG_MIME = DRAG_MIME;
