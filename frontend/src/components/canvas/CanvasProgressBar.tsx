// Phase 8.1 — ETL Canvas 6단계 진행 바.
//
// 사용자가 캔버스에서 어떤 단계까지 자산을 배치했는지 한 눈에 볼 수 있도록.
import { CheckCircle2, Circle } from "lucide-react";
import type { NodeType } from "@/api/pipelines";
import { cn } from "@/lib/cn";

interface Step {
  label: string;
  matchTypes: NodeType[];
}

const STEPS: Step[] = [
  {
    label: "1. 수집",
    matchTypes: [
      "SOURCE_DATA",
      "PUBLIC_API_FETCH",
      "WEBHOOK_INGEST",
      "FILE_UPLOAD_INGEST",
      "DB_INCREMENTAL_FETCH",
      "OCR_RESULT_INGEST",
      "CRAWLER_RESULT_INGEST",
      "OCR_TRANSFORM",
      "CRAWL_FETCH",
      "SOURCE_API",
    ],
  },
  {
    label: "2. 매핑",
    matchTypes: ["MAP_FIELDS"],
  },
  {
    label: "3. 정제·표준화",
    matchTypes: [
      "SQL_INLINE_TRANSFORM",
      "SQL_ASSET_TRANSFORM",
      "HTTP_TRANSFORM",
      "FUNCTION_TRANSFORM",
      "STANDARDIZE",
      "SQL_TRANSFORM",
    ],
  },
  {
    label: "4. DQ",
    matchTypes: ["DQ_CHECK", "DEDUP"],
  },
  {
    label: "5. 마트 적재",
    matchTypes: ["LOAD_TARGET", "LOAD_MASTER"],
  },
  {
    label: "6. 검증·배포",
    matchTypes: ["NOTIFY"],  // PUBLISH/Dry-run 은 toolbar 가 별도 표시
  },
];

interface CanvasProgressBarProps {
  nodeTypes: NodeType[];
}

export function CanvasProgressBar({ nodeTypes }: CanvasProgressBarProps) {
  const presentSet = new Set(nodeTypes);

  return (
    <div className="flex items-center gap-1 rounded-md border border-border bg-background p-2 text-xs">
      {STEPS.map((step, idx) => {
        const isFilled = step.matchTypes.some((t) => presentSet.has(t));
        return (
          <div key={step.label} className="flex flex-1 items-center gap-1">
            <div
              className={cn(
                "flex items-center gap-1 rounded-md px-2 py-1",
                isFilled
                  ? "bg-primary/10 text-primary font-semibold"
                  : "text-muted-foreground",
              )}
            >
              {isFilled ? (
                <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
              ) : (
                <Circle className="h-3.5 w-3.5" />
              )}
              <span className="whitespace-nowrap">{step.label}</span>
            </div>
            {idx < STEPS.length - 1 && (
              <div
                className={cn(
                  "h-0.5 flex-1",
                  isFilled ? "bg-primary/30" : "bg-border",
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
