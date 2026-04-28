import { AlertTriangle, ClipboardCheck, Eye, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export function ReviewQueueV2() {
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Review Queue</h2>
        <p className="max-w-4xl text-sm text-muted-foreground">
          OCR, 크롤링, 사용자 입력처럼 신뢰도 편차가 있는 데이터는 자동 적재 전에 검수 큐로
          보냅니다. 표준 매칭 실패, 가격 급변, DQ 실패, 낮은 confidence를 사람이 승인/수정/반려합니다.
        </p>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        <Card>
          <CardContent className="space-y-3 p-4">
            <ShieldAlert className="h-5 w-5 text-amber-600" />
            <div className="font-semibold">검수 대상 조건</div>
            <p className="text-sm leading-6 text-muted-foreground">
              낮은 OCR confidence, 상품 표준 매칭 실패, 전일 대비 과도한 가격 변동, 사용자 입력 오류를 큐로 보냅니다.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-3 p-4">
            <Eye className="h-5 w-5 text-primary" />
            <div className="font-semibold">사람의 판단</div>
            <p className="text-sm leading-6 text-muted-foreground">
              원본 payload와 표준화 후보를 보고 승인, 수정, 반려합니다. 승인된 데이터만 마트 적재로 진행합니다.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-3 p-4">
            <ClipboardCheck className="h-5 w-5 text-emerald-600" />
            <div className="font-semibold">현재 연결</div>
            <p className="text-sm leading-6 text-muted-foreground">
              기존 Crowd Task / DQ Hold 화면과 연결해 운영 검수 흐름을 통합할 예정입니다.
            </p>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <span className="text-sm text-muted-foreground">
            다음 실증에서는 Review Queue 항목 생성 API와 표준화 후보 수정 UI를 붙이면 됩니다.
          </span>
          <Link to="/crowd-tasks" className="ml-auto">
            <Button variant="outline">기존 검수 큐 보기</Button>
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
