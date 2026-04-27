// Phase 8.6 — Dashboard Quick Start 카드 (도메인 무관 공용 표현).
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronRight, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { apiRequest } from "@/api/client";
import { Card, CardContent } from "@/components/ui/card";

interface OnboardingStep {
  code: string;
  label: string;
  completed: boolean;
  count: number;
  next_action_label: string;
  next_action_href: string;
  help_summary: string;
}

interface OnboardingProgress {
  steps: OnboardingStep[];
  completed_count: number;
  total: number;
  is_ready: boolean;
}

export function QuickStartCard() {
  const q = useQuery({
    queryKey: ["v2-onboarding-progress"],
    queryFn: () => apiRequest<OnboardingProgress>("/v2/onboarding/progress"),
    refetchInterval: 60_000,
  });

  if (q.isLoading || !q.data) return null;
  const { steps, completed_count, total, is_ready } = q.data;
  const pct = Math.round((completed_count / total) * 100);

  return (
    <Card
      className={
        is_ready
          ? "border-emerald-300 bg-emerald-50"
          : "border-blue-300 bg-blue-50"
      }
    >
      <CardContent className="space-y-3 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles
              className={`h-4 w-4 ${
                is_ready ? "text-emerald-600" : "text-blue-600"
              }`}
            />
            <h3 className="text-sm font-semibold">
              {is_ready
                ? "✓ 준비 완료 — 모든 단계가 활성화되어 있습니다"
                : `Quick Start (${completed_count}/${total} 완료)`}
            </h3>
          </div>
          <span
            className={`text-[10px] font-semibold ${
              is_ready ? "text-emerald-700" : "text-blue-700"
            }`}
          >
            {pct}%
          </span>
        </div>
        {!is_ready && (
          <p className="text-xs text-muted-foreground">
            아래 5 단계를 순서대로 완료하면 첫 데이터 흐름이 동작합니다.
            (이 시스템은 도메인 무관 공용 플랫폼 — 어떤 외부 데이터든 동일 절차)
          </p>
        )}
        <div
          className={`h-1.5 w-full overflow-hidden rounded-full ${
            is_ready ? "bg-emerald-200" : "bg-blue-200"
          }`}
        >
          <div
            className={`h-full transition-all ${
              is_ready ? "bg-emerald-600" : "bg-blue-600"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <ol className="space-y-1.5">
          {steps.map((s, idx) => (
            <li key={s.code}>
              <Link
                to={s.next_action_href}
                className={`flex items-center gap-2 rounded-md border px-2 py-1.5 text-xs transition-colors ${
                  s.completed
                    ? "border-emerald-200 bg-emerald-50/50 text-emerald-700 hover:bg-emerald-100/50"
                    : "border-border bg-background hover:bg-secondary"
                }`}
                title={s.help_summary}
              >
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                    s.completed
                      ? "bg-emerald-600 text-white"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {s.completed ? <Check className="h-3 w-3" /> : idx + 1}
                </span>
                <span className="flex-1 font-medium">{s.label}</span>
                {s.completed ? (
                  <span className="text-[10px] text-emerald-700">
                    {s.count}건
                  </span>
                ) : (
                  <span className="text-[10px] text-primary">
                    {s.next_action_label}
                  </span>
                )}
                <ChevronRight className="h-3 w-3 text-muted-foreground" />
              </Link>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}
