import { ArrowRight, Sparkles } from "lucide-react";
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
                <NodePill label="SOURCE_DATA" hint="원천 데이터 선택" />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="MAP_FIELDS" hint="필드 매핑" highlight />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="FUNCTION_TRANSFORM" hint="함수 변환" optional />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="STANDARDIZE" hint="표준화" optional />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="DQ_CHECK" hint="품질 검증" />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="LOAD_TARGET" hint="적재" highlight />
              </div>
            </div>
            <p className="text-[10px] text-muted-foreground">
              필수 박스부터 캔버스에 올린 뒤, 각 박스의 설정 패널에서 사용할 자산을
              선택하세요.
            </p>
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
  optional = false,
}: {
  label: string;
  hint: string;
  highlight?: boolean;
  optional?: boolean;
}) {
  return (
    <div
      className={`flex flex-col items-center rounded-md border px-2 py-1 ${
        highlight
          ? "border-blue-500 bg-blue-100 font-semibold text-blue-800"
          : optional
            ? "border-dashed border-zinc-300 bg-white italic text-muted-foreground"
            : "border-zinc-300 bg-white"
      }`}
      title={hint}
    >
      <span className="font-mono">{label}</span>
      <span className="mt-0.5 text-[9px] text-muted-foreground">{hint}</span>
    </div>
  );
}
