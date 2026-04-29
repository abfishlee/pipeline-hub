import { ArrowRight, GitMerge, Sparkles } from "lucide-react";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";

export function CanvasPatternHint() {
  const [open, setOpen] = useState(true);

  return (
    <Card className="border-blue-200 bg-blue-50/40">
      <CardContent className="space-y-3 p-3">
        <div className="flex items-center justify-between gap-3">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-blue-700">
            <Sparkles className="h-3.5 w-3.5" />
            권장 패턴
          </h3>
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="text-[10px] text-blue-700 hover:underline"
          >
            {open ? "접기" : "펼치기"}
          </button>
        </div>
        {open && (
          <>
            <div className="overflow-x-auto">
              <div className="flex min-w-max items-center gap-1 text-[11px]">
                <NodePill label="SOURCE" hint="API Pull / Inbound" />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="MAP_FIELDS" hint="JSONB 평탄화" highlight />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="SQL MODEL" hint="대량 변환" />
                <NodePill label="PYTHON MODEL" hint="복잡한 파싱" />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="LOAD_TARGET" hint="마트 적재" highlight />
              </div>
            </div>
            <div className="flex gap-2 rounded-md bg-white/70 p-2 text-[10px] leading-4 text-muted-foreground">
              <GitMerge className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-700" />
              <p>
                노드는 첫 노드를 기준으로 격자에 정렬됩니다. 같은 열의 여러 노드는 병렬 단계로
                배치하기 좋고, 실행 순서는 선(edge)으로 결정됩니다. 한 노드에 선행 노드가 2개
                이상 연결되면 모든 선행 노드가 성공해야 다음 노드가 실행됩니다.
              </p>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function NodePill({
  label,
  hint,
  highlight = false,
}: {
  label: string;
  hint: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`flex flex-col items-center rounded-md border px-2 py-1 ${
        highlight
          ? "border-blue-500 bg-blue-100 font-semibold text-blue-800"
          : "border-zinc-300 bg-white"
      }`}
      title={hint}
    >
      <span className="font-mono">{label}</span>
      <span className="mt-0.5 text-[9px] text-muted-foreground">{hint}</span>
    </div>
  );
}
