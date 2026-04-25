import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

const DEFAULT_GRAFANA_URL =
  (import.meta.env.VITE_GRAFANA_URL as string | undefined) ??
  "http://localhost:3000";
const RUNTIME_DASHBOARD_PATH = "/d/pipeline-hub-runtime?orgId=1&kiosk=tv";
const CORE_DASHBOARD_PATH = "/d/pipeline-hub-core?orgId=1&kiosk=tv";

export function RuntimeMonitor() {
  const [grafanaBase, setGrafanaBase] = useState(DEFAULT_GRAFANA_URL);
  const [tab, setTab] = useState<"runtime" | "core">("runtime");

  const path = tab === "runtime" ? RUNTIME_DASHBOARD_PATH : CORE_DASHBOARD_PATH;
  const iframeSrc = `${grafanaBase.replace(/\/$/, "")}${path}`;

  return (
    <div className="flex h-full flex-col gap-4">
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Grafana base URL</label>
            <Input
              className="w-72"
              value={grafanaBase}
              onChange={(e) => setGrafanaBase(e.target.value)}
              placeholder="http://localhost:3000"
            />
          </div>
          <div className="flex gap-2">
            <Button
              variant={tab === "runtime" ? "default" : "outline"}
              size="sm"
              onClick={() => setTab("runtime")}
            >
              Runtime
            </Button>
            <Button
              variant={tab === "core" ? "default" : "outline"}
              size="sm"
              onClick={() => setTab("core")}
            >
              Core (Phase 1)
            </Button>
            <a
              className="text-xs text-primary underline"
              href={iframeSrc.replace("&kiosk=tv", "")}
              target="_blank"
              rel="noopener noreferrer"
            >
              새 창으로 열기
            </a>
          </div>
          <p className="basis-full text-xs text-muted-foreground">
            ※ Grafana 가 다른 호스트에 있거나 인증이 걸려 있으면 iframe 이 빈
            화면이 됩니다. `VITE_GRAFANA_URL` 환경변수로 기본값을 설정하거나
            상단 입력란을 조정하세요. 운영(NKS) 에서는 SSO 토큰이 필요합니다.
          </p>
        </CardContent>
      </Card>

      <Card className="flex-1">
        <CardContent className="h-full p-0">
          <iframe
            key={iframeSrc}
            title="Grafana Dashboard"
            src={iframeSrc}
            className="h-full min-h-[600px] w-full rounded-md border-0"
            sandbox="allow-scripts allow-same-origin"
          />
        </CardContent>
      </Card>
    </div>
  );
}
