// Phase 8.6 — 페이지별 인라인 도움말 (?) 버튼 + 우측 drawer.
import { HelpCircle, X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";

export interface HelpDrawerProps {
  pageTitle: string;
  summary: string;
  steps?: string[];
  tips?: string[];
  related?: Array<{ label: string; href: string }>;
}

export function HelpDrawer({
  pageTitle,
  summary,
  steps = [],
  tips = [],
  related = [],
}: HelpDrawerProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => setOpen(true)}
        title={`${pageTitle} 도움말`}
        className="gap-1"
      >
        <HelpCircle className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">도움말</span>
      </Button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex justify-end bg-black/30"
          onClick={() => setOpen(false)}
        >
          <aside
            className="flex h-full w-full max-w-md flex-col gap-3 overflow-y-auto bg-background p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div>
                <p className="text-[10px] font-semibold uppercase text-muted-foreground">
                  도움말
                </p>
                <h2 className="text-lg font-semibold">{pageTitle}</h2>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md p-1 hover:bg-secondary"
                title="닫기"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="text-sm leading-6 text-muted-foreground">{summary}</p>
            {steps.length > 0 && (
              <section className="space-y-1">
                <h3 className="text-sm font-semibold">진행 순서</h3>
                <ol className="ml-4 list-decimal space-y-1 text-xs leading-5 text-muted-foreground">
                  {steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              </section>
            )}
            {tips.length > 0 && (
              <section className="space-y-1">
                <h3 className="text-sm font-semibold">팁</h3>
                <ul className="ml-4 list-disc space-y-1 text-xs leading-5 text-muted-foreground">
                  {tips.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </section>
            )}
            {related.length > 0 && (
              <section className="space-y-1">
                <h3 className="text-sm font-semibold">관련 화면</h3>
                <ul className="space-y-0.5 text-xs">
                  {related.map((r) => (
                    <li key={r.href}>
                      <a
                        href={r.href}
                        className="text-primary hover:underline"
                        onClick={() => setOpen(false)}
                      >
                        {r.label} →
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <div className="mt-auto rounded-md border border-dashed border-border bg-muted/30 p-2 text-[10px] text-muted-foreground">
              ※ 도움말은 Phase 8.6 — 자세한 매뉴얼은{" "}
              <code>docs/manual/PHASE_8_SCENARIO_MANUAL.pdf</code>.
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
