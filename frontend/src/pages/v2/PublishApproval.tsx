// Phase 6 Wave 5 — Publish Approval (Mini Checklist + ADMIN 승인).
//
// 사용자 시나리오:
//   1. 자산 (mapping / sql_asset / load_policy / dq_rule / source_contract) 의
//      "Publish 검토" 버튼 → 본 페이지
//   2. /v2/checklist/run → 7 항목 자동 평가 (PASS/FAIL)
//   3. all_passed 면 ADMIN 의 "PUBLISH 승인" 버튼 enable → 해당 자산 transition →PUBLISHED
//   4. 최근 checklist 이력 목록도 함께 표시
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ListChecks,
  Send,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { useTransitionMapping } from "@/api/v2/mappings";
import { useTransitionLoadPolicy } from "@/api/v2/load_policies";
import { useTransitionSqlAsset } from "@/api/v2/sql_assets";
import {
  type ChecklistOut,
  type EntityType,
  useRecentChecklists,
  useRunChecklist,
} from "@/api/v2/dryrun";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useAuthStore } from "@/store/auth";
import { formatDateTime } from "@/lib/format";

const ENTITY_LABELS: Record<EntityType, string> = {
  source_contract: "Source Contract",
  field_mapping: "Field Mapping",
  dq_rule: "DQ Rule",
  mart_load_policy: "Mart Load Policy",
  sql_asset: "SQL Asset",
  load_policy: "Load Policy",
};

export function PublishApproval() {
  const params = useParams<{ entityType?: string; entityId?: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAdmin = !!user?.roles.includes("ADMIN");

  const entityType = (params.entityType ?? "") as EntityType | "";
  const entityId = params.entityId ? Number(params.entityId) : null;
  const version = Number(searchParams.get("v") ?? "1");
  const domainCode = searchParams.get("domain") ?? null;
  const targetTable = searchParams.get("target_table") ?? null;
  const contractId = searchParams.get("contract_id");

  const runChecklist = useRunChecklist();
  const recent = useRecentChecklists({
    entity_type: entityType || undefined,
    limit: 5,
  });
  const transitionMapping = useTransitionMapping(entityId ?? 0);
  const transitionLoadPolicy = useTransitionLoadPolicy(entityId ?? 0);
  const transitionSqlAsset = useTransitionSqlAsset(entityId ?? 0);

  const [outcome, setOutcome] = useState<ChecklistOut | null>(null);

  async function runNow() {
    if (!entityType || !entityId) {
      toast.error("entity_type / entity_id 필수");
      return;
    }
    try {
      const res = await runChecklist.mutateAsync({
        entity_type: entityType,
        entity_id: entityId,
        entity_version: version,
        domain_code: domainCode,
        target_table: targetTable,
        contract_id: contractId ? Number(contractId) : null,
      });
      setOutcome(res);
      toast.success(
        res.all_passed
          ? `checklist 통과 (${res.checks.length}/${res.checks.length}) — ADMIN 승인 가능`
          : `checklist ${res.failed_check_codes.length}개 실패 — 수정 후 재시도`,
      );
      void recent.refetch();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`checklist 실패: ${msg}`);
    }
  }

  useEffect(() => {
    if (entityType && entityId && !outcome && !runChecklist.isPending) {
      void runNow();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityType, entityId]);

  async function handlePublish() {
    if (!entityId || !outcome?.all_passed) return;
    if (!isAdmin) {
      toast.error("ADMIN 권한이 필요합니다.");
      return;
    }
    try {
      switch (entityType) {
        case "field_mapping":
          await transitionMapping.mutateAsync("PUBLISHED");
          break;
        case "load_policy":
        case "mart_load_policy":
          await transitionLoadPolicy.mutateAsync("PUBLISHED");
          break;
        case "sql_asset":
          await transitionSqlAsset.mutateAsync("PUBLISHED");
          break;
        default:
          toast.error(
            `${entityType} 의 transition 은 본 화면에서 지원하지 않습니다. 해당 designer 에서 직접 진행해 주세요.`,
          );
          return;
      }
      toast.success(`${ENTITY_LABELS[entityType as EntityType]} → PUBLISHED`);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`PUBLISH 실패: ${msg}`);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate(-1)}>
          <ArrowLeft className="h-4 w-4" />
          돌아가기
        </Button>
        <h2 className="text-lg font-semibold">
          Publish Approval —{" "}
          {entityType ? ENTITY_LABELS[entityType as EntityType] : ""} #
          {entityId} v{version}
        </h2>
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
          <Button
            onClick={runNow}
            disabled={runChecklist.isPending || !entityType || !entityId}
            variant="outline"
          >
            <ListChecks className="h-4 w-4" />
            {runChecklist.isPending ? "실행 중..." : "Checklist 재실행"}
          </Button>

          {outcome && (
            <Badge
              variant={outcome.all_passed ? "success" : "destructive"}
            >
              {outcome.all_passed
                ? "all passed"
                : `${outcome.failed_check_codes.length}개 실패`}
            </Badge>
          )}

          <Button
            onClick={handlePublish}
            disabled={
              !outcome?.all_passed ||
              !isAdmin ||
              transitionMapping.isPending ||
              transitionLoadPolicy.isPending ||
              transitionSqlAsset.isPending
            }
            className="ml-auto"
          >
            <Send className="h-4 w-4" />
            ADMIN 승인 → PUBLISH
          </Button>

          {!isAdmin && (
            <span className="basis-full text-xs text-muted-foreground">
              ※ PUBLISHED 전이는 ADMIN 권한 필요. 현재 사용자는 view-only.
            </span>
          )}
        </CardContent>
      </Card>

      {outcome && (
        <Card>
          <CardContent className="space-y-2 p-4">
            <div className="text-xs font-semibold uppercase text-muted-foreground">
              Checklist 결과 ({outcome.checks.length} 항목)
            </div>
            <div className="space-y-1">
              {outcome.checks.map((c) => (
                <div
                  key={c.code}
                  className="flex items-start gap-2 rounded-md border border-border p-2"
                >
                  {c.passed ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 text-green-600" />
                  ) : (
                    <XCircle className="mt-0.5 h-4 w-4 text-destructive" />
                  )}
                  <div className="flex-1">
                    <div className="text-xs font-mono font-semibold">
                      {c.code}
                    </div>
                    {c.detail && (
                      <div className="text-xs text-muted-foreground">
                        {c.detail}
                      </div>
                    )}
                    {Object.keys(c.metadata).length > 0 && (
                      <pre className="mt-1 overflow-auto rounded bg-muted/40 p-1 text-[10px]">
                        {JSON.stringify(c.metadata, null, 0)}
                      </pre>
                    )}
                  </div>
                  <Badge variant={c.passed ? "success" : "destructive"}>
                    {c.passed ? "PASS" : "FAIL"}
                  </Badge>
                </div>
              ))}
            </div>

            {!outcome.all_passed && (
              <div className="mt-2 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs">
                <AlertTriangle className="h-4 w-4 text-amber-700" />
                <div>
                  실패한 체크: <code>{outcome.failed_check_codes.join(", ")}</code>
                  <br />
                  자산을 수정 후 다시 checklist 를 실행하세요.
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="space-y-2 p-4">
          <div className="text-xs font-semibold uppercase text-muted-foreground">
            최근 checklist 이력
          </div>
          {recent.isLoading && (
            <div className="text-xs text-muted-foreground">불러오는 중...</div>
          )}
          {recent.data && recent.data.length === 0 && (
            <div className="text-xs text-muted-foreground">이력 없음</div>
          )}
          {recent.data &&
            recent.data.map((r) => (
              <div
                key={r.checklist_id ?? `${r.entity_type}-${r.entity_id}-${r.requested_at}`}
                className="flex items-center gap-2 rounded-md border border-border p-2 text-xs"
              >
                <Badge variant={r.all_passed ? "success" : "destructive"}>
                  {r.all_passed ? "PASS" : "FAIL"}
                </Badge>
                <span className="font-mono">
                  {r.entity_type} #{r.entity_id} v{r.entity_version}
                </span>
                <span className="text-muted-foreground">
                  · {r.checks.length} 항목
                </span>
                <span className="ml-auto text-muted-foreground">
                  {formatDateTime(r.requested_at)}
                </span>
              </div>
            ))}
        </CardContent>
      </Card>
    </div>
  );
}
