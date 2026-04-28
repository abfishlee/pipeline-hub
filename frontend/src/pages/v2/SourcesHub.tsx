import {
  ArrowRight,
  Bot,
  ClipboardList,
  FileInput,
  Globe,
  UploadCloud,
  Webhook,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";

const sourceTypes = [
  {
    title: "API Pull",
    desc: "우리가 외부 REST/JSON/XML/CSV API를 주기적으로 호출합니다.",
    to: "/v2/connectors/public-api",
    icon: Globe,
    action: "Source/API 등록",
  },
  {
    title: "Webhook Push",
    desc: "외부 시스템이 데이터 변경 이벤트나 결과 payload를 우리에게 보냅니다.",
    to: "/v2/inbound-channels/designer",
    icon: Webhook,
    action: "Inbound Channel 등록",
  },
  {
    title: "File Upload",
    desc: "CSV, Excel, JSON 파일을 업로드하고 공통 파이프라인으로 태웁니다.",
    to: "/v2/inbound-channels/designer",
    icon: FileInput,
    action: "업로드 채널 등록",
  },
  {
    title: "OCR Result",
    desc: "외부 OCR 업체의 인식 결과를 수신해 검수와 표준화를 거칩니다.",
    to: "/v2/inbound-channels/designer",
    icon: ClipboardList,
    action: "OCR 채널 등록",
  },
  {
    title: "Crawler Result",
    desc: "크롤러가 수집한 웹 가격 데이터를 push하거나 수집 Job으로 처리합니다.",
    to: "/v2/inbound-channels/designer",
    icon: Bot,
    action: "크롤링 채널 등록",
  },
  {
    title: "Manual Input",
    desc: "운영자가 직접 입력한 가격 정보를 검수 큐와 마트 적재 흐름에 연결합니다.",
    to: "/v2/review-queue",
    icon: UploadCloud,
    action: "검수 큐 보기",
  },
];

export function SourcesHub() {
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Sources</h2>
        <p className="max-w-4xl text-sm text-muted-foreground">
          API, webhook, 파일, OCR, 크롤링, 직접 입력을 모두 데이터파이프라인의 앞단
          원천으로 관리합니다. 원천은 이후 계약, 매핑, 표준화, 품질검사, 마트 적재로 이어집니다.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {sourceTypes.map((item) => (
          <Link key={item.title} to={item.to}>
            <Card className="h-full transition hover:border-primary/50 hover:bg-muted/30">
              <CardContent className="flex h-full flex-col gap-4 p-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <item.icon className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="font-semibold">{item.title}</div>
                    <p className="mt-1 text-sm leading-6 text-muted-foreground">
                      {item.desc}
                    </p>
                  </div>
                </div>
                <div className="mt-auto flex items-center gap-2 text-sm font-medium text-primary">
                  {item.action}
                  <ArrowRight className="h-4 w-4" />
                </div>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
