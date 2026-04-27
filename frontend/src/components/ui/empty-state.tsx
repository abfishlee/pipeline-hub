// Phase 8.6 — 공통 EmptyState 컴포넌트.
//
// 모든 디자이너 / 목록 페이지에서 "데이터 없음" 표시를 일관되게 처리:
// 아이콘 + 제목 + 설명 + 다음 액션 버튼 + 도움말 링크.
import { ExternalLink, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  primaryAction?: { label: string; onClick: () => void; disabled?: boolean };
  secondaryAction?: { label: string; onClick: () => void };
  learnMoreHref?: string;
  learnMoreLabel?: string;
  compact?: boolean;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  primaryAction,
  secondaryAction,
  learnMoreHref,
  learnMoreLabel = "도움말",
  compact = false,
}: EmptyStateProps) {
  const content = (
    <>
      {Icon && (
        <div className="rounded-full bg-muted/50 p-3">
          <Icon className="h-7 w-7 text-muted-foreground" />
        </div>
      )}
      <div className="space-y-1">
        <h3 className={compact ? "text-sm font-medium" : "text-base font-semibold"}>
          {title}
        </h3>
        {description && (
          <p className="max-w-md text-xs text-muted-foreground">{description}</p>
        )}
      </div>
      <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
        {primaryAction && (
          <Button
            size={compact ? "sm" : "md"}
            onClick={primaryAction.onClick}
            disabled={primaryAction.disabled}
          >
            {primaryAction.label}
          </Button>
        )}
        {secondaryAction && (
          <Button
            size={compact ? "sm" : "md"}
            variant="outline"
            onClick={secondaryAction.onClick}
          >
            {secondaryAction.label}
          </Button>
        )}
        {learnMoreHref && (
          <a
            href={learnMoreHref}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            {learnMoreLabel}
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </>
  );
  if (compact) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
        {content}
      </div>
    );
  }
  return (
    <Card>
      <CardContent className="flex flex-col items-center justify-center gap-3 py-12 text-center">
        {content}
      </CardContent>
    </Card>
  );
}
