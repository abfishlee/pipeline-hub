import { CheckCircle2, GitMerge, Ruler, ScanSearch } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

const items = [
  {
    icon: ScanSearch,
    title: "상품명 표준화",
    desc: "원천별 상품명을 표준상품 후보와 매칭하고 신뢰도를 관리합니다.",
  },
  {
    icon: Ruler,
    title: "단위/규격 정규화",
    desc: "g, kg, ml, L, 묶음 단위를 서비스 기준 단위로 변환합니다.",
  },
  {
    icon: GitMerge,
    title: "원천 통합",
    desc: "API, OCR, 크롤링, 사용자 입력을 동일한 표준 스키마로 맞춥니다.",
  },
  {
    icon: CheckCircle2,
    title: "검수 기준",
    desc: "표준 매칭 실패, 낮은 OCR confidence, 가격 급변을 Review Queue로 보냅니다.",
  },
];

export function StandardizationWorkbench() {
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Standardization</h2>
        <p className="max-w-4xl text-sm text-muted-foreground">
          여러 원천에서 들어온 가격/상품 데이터를 서비스 마트가 사용할 수 있는 공통 기준으로
          정규화합니다. 현재는 메뉴 골격을 추가했고, 다음 실증에서 상품 표준 매칭과 단위 변환
          기능을 붙이면 됩니다.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((item) => (
          <Card key={item.title}>
            <CardContent className="flex gap-3 p-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                <item.icon className="h-5 w-5" />
              </div>
              <div>
                <div className="font-semibold">{item.title}</div>
                <p className="mt-1 text-sm leading-6 text-muted-foreground">
                  {item.desc}
                </p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
