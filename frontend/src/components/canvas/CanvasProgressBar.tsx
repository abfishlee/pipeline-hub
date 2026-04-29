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
    label: "2. 평탄화",
    matchTypes: ["MAP_FIELDS"],
  },
  {
    label: "3. 모형 처리",
    matchTypes: [
      "SQL_INLINE_TRANSFORM",
      "SQL_ASSET_TRANSFORM",
      "PYTHON_MODEL_TRANSFORM",
      "HTTP_TRANSFORM",
      "FUNCTION_TRANSFORM",
      "STANDARDIZE",
      "SQL_TRANSFORM",
    ],
  },
  {
    label: "4. 검증",
    matchTypes: ["DQ_CHECK", "DEDUP"],
  },
  {
    label: "5. 마트 적재",
    matchTypes: ["LOAD_TARGET", "LOAD_MASTER"],
  },
  {
    label: "6. 알림",
    matchTypes: ["NOTIFY"],
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
                isFilled ? "bg-primary/10 font-semibold text-primary" : "text-muted-foreground",
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
              <div className={cn("h-0.5 flex-1", isFilled ? "bg-primary/30" : "bg-border")} />
            )}
          </div>
        );
      })}
    </div>
  );
}
