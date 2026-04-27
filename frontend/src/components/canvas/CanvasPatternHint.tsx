// Phase 8.6 — ETL Canvas 권장 패턴 + 평탄화 stg 흐름 시각화.
//
// 신규 사용자가 Canvas 진입 시 어떤 노드를 어떤 순서로 끌어다 놓아야 하는지 안내.
// "JSONB → 평탄화 stg → 표준화 → 최종 mart" 3 단계 마트 개념을 명확히 함.
import { ArrowRight, Database, FileText, Layers, Sparkles } from "lucide-react";
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";

export function CanvasPatternHint() {
  const [open, setOpen] = useState(true);

  return (
    <Card className="border-blue-200 bg-blue-50/40">
      <CardContent className="space-y-3 p-3">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-blue-700">
            <Sparkles className="h-3.5 w-3.5" />
            권장 패턴 — 외부 데이터 → 표준 마트 흐름
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
            {/* 노드 chain — 권장 순서 */}
            <div className="overflow-x-auto">
              <div className="flex min-w-max items-center gap-1 text-[11px]">
                <NodePill label="SOURCE_DATA" hint="raw_object 읽기" />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill
                  label="MAP_FIELDS"
                  hint="평탄화 (path → 컬럼)"
                  highlight
                />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill
                  label="FUNCTION_TRANSFORM"
                  hint="행 단위 추가 변환"
                  optional
                />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="STANDARDIZE" hint="표준코드 매칭" optional />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="DQ_CHECK" hint="품질 검증" />
                <ArrowRight className="h-3 w-3 text-muted-foreground" />
                <NodePill label="LOAD_TARGET" hint="최종 마트 적재" highlight />
              </div>
            </div>

            {/* 평탄화 stg → 최종 mart 3 단계 도식 */}
            <div className="rounded-md border border-blue-200 bg-white p-2">
              <p className="mb-1.5 text-[11px] font-semibold text-blue-700">
                📦 마트 schema 3 단계
              </p>
              <div className="grid grid-cols-3 gap-2 text-[10px]">
                <SchemaBox
                  icon={<FileText className="h-3 w-3" />}
                  title="① 임시 sandbox"
                  schema="wf.tmp_run_*"
                  desc="Canvas 실행 중 노드 간 데이터 전달용. 매 run 마다 새로 생성, 이전 run 미보존."
                  tone="muted"
                />
                <SchemaBox
                  icon={<Layers className="h-3 w-3" />}
                  title="② 평탄화 stg"
                  schema="<domain>_stg.*"
                  desc="JSONB 평탄화 결과 영구 보존. 표준코드 매칭 / 구간화 직전 상태. 재처리 시 재사용 가능."
                  tone="amber"
                />
                <SchemaBox
                  icon={<Database className="h-3 w-3" />}
                  title="③ 최종 mart"
                  schema="<domain>_mart.*"
                  desc="외부 서비스에 노출되는 표준화 + 검증 완료 데이터. 표준코드 / 단위 / 등급 정규화 끝."
                  tone="emerald"
                />
              </div>
              <p className="mt-1.5 text-[9px] text-muted-foreground">
                ※ MAP_FIELDS 노드의 target_table 에 위 3 schema 모두 입력 가능. 사용자가
                의도적으로 stg 를 거쳐 SQL_ASSET_TRANSFORM / STANDARDIZE 로 후처리하는 것을 권장.
              </p>
            </div>

            <p className="text-[10px] text-muted-foreground">
              <span className="font-semibold text-blue-700">★ 굵은 노드</span> = 거의 모든 워크플로
              에서 필수, <span className="italic">기울임</span> = 도메인/요구사항에 따라 선택.
              자세한 노드 카탈로그는 도움말 참고.
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

function SchemaBox({
  icon,
  title,
  schema,
  desc,
  tone,
}: {
  icon: React.ReactNode;
  title: string;
  schema: string;
  desc: string;
  tone: "muted" | "amber" | "emerald";
}) {
  const cls = {
    muted: "border-zinc-200 bg-zinc-50",
    amber: "border-amber-200 bg-amber-50",
    emerald: "border-emerald-200 bg-emerald-50",
  }[tone];
  return (
    <div className={`rounded-md border ${cls} p-1.5`}>
      <div className="flex items-center gap-1 font-semibold">
        {icon}
        {title}
      </div>
      <code className="mt-0.5 block font-mono text-[9px]">{schema}</code>
      <p className="mt-1 text-[9px] leading-3 text-muted-foreground">{desc}</p>
    </div>
  );
}
