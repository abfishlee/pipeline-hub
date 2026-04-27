import { useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ListChecks,
  Loader2,
  Plus,
  Send,
  ShieldCheck,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  type SqlQueryVersionOut,
  type SqlVersionStatus,
  useAddSqlVersion,
  useApproveSqlVersion,
  useCreateSqlQuery,
  useExplainSql,
  usePreviewSql,
  useRejectSqlVersion,
  useSqlQueries,
  useSqlQueryDetail,
  useSubmitSqlVersion,
  useValidateSql,
} from "@/api/sql_studio";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/store/auth";

const STATUS_BADGE: Record<
  SqlVersionStatus,
  "default" | "muted" | "success" | "destructive" | "warning"
> = {
  DRAFT: "muted",
  PENDING: "warning",
  APPROVED: "success",
  REJECTED: "destructive",
  SUPERSEDED: "muted",
};

type Tab = "result" | "explain" | "refs";

export function SqlStudio() {
  const queries = useSqlQueries();
  const [selectedQueryId, setSelectedQueryId] = useState<number | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<number | null>(null);
  const detail = useSqlQueryDetail(selectedQueryId);

  const [sql, setSql] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("result");

  const validate = useValidateSql();
  const preview = usePreviewSql();
  const explain = useExplainSql();
  const submit = useSubmitSqlVersion();
  const approve = useApproveSqlVersion();
  const reject = useRejectSqlVersion();
  const addVersion = useAddSqlVersion();

  const user = useAuthStore((s) => s.user);
  const isApprover = !!user?.roles.some(
    (r) => r === "ADMIN" || r === "APPROVER",
  );
  const qc = useQueryClient();

  const selectedVersion = useMemo<SqlQueryVersionOut | null>(() => {
    if (!detail.data) return null;
    if (selectedVersionId) {
      return (
        detail.data.versions.find(
          (v) => v.sql_query_version_id === selectedVersionId,
        ) ?? null
      );
    }
    // 최신 버전 자동 선택.
    return detail.data.versions[detail.data.versions.length - 1] ?? null;
  }, [detail.data, selectedVersionId]);

  // 버전 변경 시 editor 본문 동기화.
  useEffect(() => {
    if (selectedVersion) setSql(selectedVersion.sql_text);
  }, [selectedVersion?.sql_query_version_id]);  // eslint-disable-line react-hooks/exhaustive-deps

  // 새 query 선택 시 최신 버전으로 리셋.
  useEffect(() => {
    setSelectedVersionId(null);
  }, [selectedQueryId]);

  const handleValidate = () => {
    if (!sql.trim()) return;
    validate.mutate(sql);
  };
  const handlePreview = () => {
    if (!sql.trim()) return;
    setActiveTab("result");
    preview.mutate({
      sql,
      limit: 1000,
      sql_query_version_id: selectedVersion?.sql_query_version_id ?? null,
    });
  };
  const handleExplain = () => {
    if (!sql.trim()) return;
    setActiveTab("explain");
    explain.mutate(sql);
  };

  const isReadonlyVersion =
    !!selectedVersion && selectedVersion.status !== "DRAFT";

  const handleSaveVersion = async () => {
    if (!selectedQueryId || !selectedVersion) return;
    if (selectedVersion.status === "DRAFT") {
      // DRAFT 면 새 row 가 아니라 add_version 으로 새 DRAFT 추가 (백엔드 정책: 같은 row update X).
      try {
        const v = await addVersion.mutateAsync({
          queryId: selectedQueryId,
          sql_text: sql,
        });
        toast.success(`v${v.version_no} 저장됨 (DRAFT)`);
        setSelectedVersionId(v.sql_query_version_id);
        qc.invalidateQueries({ queryKey: ["sql-studio", "queries", selectedQueryId] });
      } catch (e) {
        toast.error(e instanceof Error ? e.message : "저장 실패");
      }
      return;
    }
    // APPROVED/REJECTED/SUPERSEDED 의 SQL 을 편집 → 새 DRAFT 로 분기.
    try {
      const v = await addVersion.mutateAsync({
        queryId: selectedQueryId,
        sql_text: sql,
      });
      toast.success(`새 DRAFT v${v.version_no} 생성됨`);
      setSelectedVersionId(v.sql_query_version_id);
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries", selectedQueryId] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "분기 실패");
    }
  };

  const handleSubmit = async () => {
    if (!selectedVersion || selectedVersion.status !== "DRAFT") return;
    try {
      await submit.mutateAsync(selectedVersion.sql_query_version_id);
      toast.success("PENDING 으로 제출됨 — 결재자 대기");
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries", selectedQueryId] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "제출 실패");
    }
  };
  const handleApprove = async () => {
    if (!selectedVersion) return;
    try {
      await approve.mutateAsync({ versionId: selectedVersion.sql_query_version_id });
      toast.success("APPROVED");
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries", selectedQueryId] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "승인 실패");
    }
  };
  const handleReject = async () => {
    if (!selectedVersion) return;
    const comment = window.prompt("반려 사유를 입력하세요 (선택)") ?? null;
    try {
      await reject.mutateAsync({
        versionId: selectedVersion.sql_query_version_id,
        comment,
      });
      toast.success("REJECTED");
      qc.invalidateQueries({ queryKey: ["sql-studio", "queries", selectedQueryId] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "반려 실패");
    }
  };

  return (
    <div className="flex h-full gap-3">
      <QuerySidebar
        queries={queries.data ?? []}
        loading={queries.isLoading}
        selectedQueryId={selectedQueryId}
        onSelect={setSelectedQueryId}
      />

      <div className="flex flex-1 flex-col gap-3">
        {/* Phase 8.6 — SQL Studio 정책 배너 */}
        <div className="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
          <strong className="font-semibold">📌 SQL Studio 정책</strong> — 본 화면은
          <em> ad-hoc 탐색</em> 도구입니다. 모든 SELECT 실행은 <code>audit.sql_execution_log</code>
          에 기록됩니다. <strong>운영 워크플로에 SQL 을 사용하려면 반드시</strong>
          {" "}<a className="underline" href="/v2/transforms/designer">Transform Designer</a>
          {" "}에서 <code>sql_asset</code> 으로 등록 → DRAFT/REVIEW/APPROVED/PUBLISHED 라이프사이클을
          거쳐야 Canvas 의 <code>SQL_ASSET_TRANSFORM</code> 노드에서 사용 가능합니다.
          이렇게 등록된 SQL 만 데이터 추적이 가능합니다.
        </div>

        {/* Header */}
        <Card>
          <CardContent className="flex flex-wrap items-center gap-3 p-3 text-sm">
            {detail.data ? (
              <>
                <h2 className="font-semibold">{detail.data.name}</h2>
                <span className="text-xs text-muted-foreground">
                  #{detail.data.sql_query_id}
                </span>
                <select
                  value={selectedVersion?.sql_query_version_id ?? ""}
                  onChange={(e) =>
                    setSelectedVersionId(
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  className="ml-2 flex h-9 rounded-md border border-input bg-background px-2 text-xs"
                >
                  {detail.data.versions.map((v) => (
                    <option key={v.sql_query_version_id} value={v.sql_query_version_id}>
                      v{v.version_no} [{v.status}]
                    </option>
                  ))}
                </select>
                {selectedVersion && (
                  <Badge variant={STATUS_BADGE[selectedVersion.status]}>
                    {selectedVersion.status}
                  </Badge>
                )}
              </>
            ) : (
              <span className="text-muted-foreground">
                좌측에서 SQL Query 를 선택하거나 신규 생성해 주세요.
              </span>
            )}

            <div className="ml-auto flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={handleValidate}
                disabled={validate.isPending || !sql.trim()}
              >
                <ShieldCheck className="h-3 w-3" /> Validate
              </Button>
              <Button
                size="sm"
                onClick={handlePreview}
                disabled={preview.isPending || !sql.trim()}
              >
                {preview.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
                Preview
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={handleExplain}
                disabled={explain.isPending || !sql.trim()}
              >
                EXPLAIN
              </Button>
              {selectedQueryId && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleSaveVersion}
                  disabled={addVersion.isPending || !sql.trim()}
                >
                  {isReadonlyVersion ? "새 DRAFT 분기" : "DRAFT 저장"}
                </Button>
              )}
              {selectedVersion?.status === "DRAFT" && (
                <Button
                  size="sm"
                  variant="default"
                  onClick={handleSubmit}
                  disabled={submit.isPending}
                >
                  <Send className="h-3 w-3" /> 제출
                </Button>
              )}
              {selectedVersion?.status === "PENDING" && isApprover && (
                <>
                  <Button
                    size="sm"
                    variant="default"
                    onClick={handleApprove}
                    disabled={approve.isPending}
                  >
                    <CheckCircle2 className="h-3 w-3" /> 승인
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    onClick={handleReject}
                    disabled={reject.isPending}
                  >
                    <X className="h-3 w-3" /> 반려
                  </Button>
                </>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Editor */}
        <Card>
          <CardContent className="space-y-2 p-3">
            <textarea
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              spellCheck={false}
              placeholder="SELECT product_id, price FROM stg.daily_prices WHERE captured_at >= now() - interval '1 day'"
              className="h-56 w-full resize-y rounded-md border border-input bg-background p-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            {validate.data && !validate.data.valid && (
              <Banner variant="error" title="검증 실패">
                <span className="font-mono">{validate.data.error}</span>
              </Banner>
            )}
            {validate.data?.valid && (
              <Banner variant="success" title="검증 통과">
                참조: {validate.data.referenced_tables.join(", ") || "없음"}
              </Banner>
            )}
            {selectedVersion?.review_comment && (
              <Banner
                variant={selectedVersion.status === "REJECTED" ? "error" : "muted"}
                title="결재자 코멘트"
              >
                {selectedVersion.review_comment}
              </Banner>
            )}
          </CardContent>
        </Card>

        {/* Result Tabs */}
        <Card className="flex-1 overflow-hidden">
          <CardContent className="flex h-full flex-col p-0">
            <div className="flex gap-1 border-b border-border bg-muted/40 px-3 py-2 text-xs">
              <TabButton active={activeTab === "result"} onClick={() => setActiveTab("result")}>
                <ListChecks className="h-3 w-3" /> 결과
                {preview.data && ` (${preview.data.row_count}${preview.data.truncated ? "+" : ""})`}
              </TabButton>
              <TabButton active={activeTab === "explain"} onClick={() => setActiveTab("explain")}>
                EXPLAIN
              </TabButton>
              <TabButton active={activeTab === "refs"} onClick={() => setActiveTab("refs")}>
                참조 테이블
              </TabButton>
              <span className="ml-auto text-[10px] text-muted-foreground">
                {preview.data && `Preview ${preview.data.elapsed_ms}ms`}
                {explain.data && `   EXPLAIN ${explain.data.elapsed_ms}ms`}
              </span>
            </div>
            <div className="flex-1 overflow-auto p-3">
              {activeTab === "result" && (
                <PreviewTable
                  loading={preview.isPending}
                  data={preview.data}
                  error={preview.error?.message}
                />
              )}
              {activeTab === "explain" && (
                <pre className="whitespace-pre-wrap font-mono text-[11px]">
                  {explain.isPending
                    ? "실행 중..."
                    : explain.data
                      ? JSON.stringify(explain.data.plan_json, null, 2)
                      : "EXPLAIN 결과 없음"}
                </pre>
              )}
              {activeTab === "refs" && (
                <div className="text-xs">
                  {selectedVersion?.referenced_tables?.length ? (
                    <ul className="list-disc pl-5">
                      {selectedVersion.referenced_tables.map((t) => (
                        <li key={t} className="font-mono">
                          {t}
                        </li>
                      ))}
                    </ul>
                  ) : validate.data?.referenced_tables.length ? (
                    <ul className="list-disc pl-5">
                      {validate.data.referenced_tables.map((t) => (
                        <li key={t} className="font-mono">
                          {t}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="text-muted-foreground">
                      Validate 또는 저장 후 참조 테이블이 표시됩니다.
                    </span>
                  )}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
interface SidebarProps {
  queries: { sql_query_id: number; name: string; updated_at: string }[];
  loading: boolean;
  selectedQueryId: number | null;
  onSelect: (id: number) => void;
}

function QuerySidebar({ queries, loading, selectedQueryId, onSelect }: SidebarProps) {
  const create = useCreateSqlQuery();
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [sql, setSql] = useState("SELECT 1 FROM mart.product LIMIT 1");

  const submit = async () => {
    if (!name.trim() || !sql.trim()) return;
    try {
      const detail = await create.mutateAsync({
        name: name.trim(),
        sql_text: sql,
      });
      toast.success(`'${detail.name}' 생성됨`);
      onSelect(detail.sql_query_id);
      setName("");
      setSql("SELECT 1 FROM mart.product LIMIT 1");
      setShowNew(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "생성 실패");
    }
  };

  return (
    <aside className="flex w-64 shrink-0 flex-col gap-2 overflow-y-auto rounded-lg border border-border bg-background p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase text-muted-foreground">
          SQL Queries
        </h3>
        <Button size="sm" variant="ghost" onClick={() => setShowNew((v) => !v)}>
          <Plus className="h-3 w-3" />
          신규
        </Button>
      </div>

      {showNew && (
        <Card>
          <CardContent className="space-y-2 p-2 text-xs">
            <Input
              placeholder="이름 (UNIQUE)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="h-8 text-xs"
            />
            <textarea
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              spellCheck={false}
              className="h-20 w-full resize-none rounded-md border border-input bg-background p-2 font-mono text-[11px]"
            />
            <Button size="sm" onClick={submit} disabled={create.isPending}>
              {create.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
              생성 (DRAFT v1)
            </Button>
          </CardContent>
        </Card>
      )}

      {loading && <p className="text-xs text-muted-foreground">로딩 중…</p>}
      {!loading && queries.length === 0 && (
        <p className="text-xs text-muted-foreground">등록된 SQL 자산이 없습니다.</p>
      )}
      <ul className="space-y-1">
        {queries.map((q) => (
          <li key={q.sql_query_id}>
            <button
              type="button"
              onClick={() => onSelect(q.sql_query_id)}
              className={cn(
                "block w-full rounded-md px-2 py-1.5 text-left text-xs transition",
                selectedQueryId === q.sql_query_id
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-secondary",
              )}
            >
              <div className="truncate font-medium">{q.name}</div>
              <div className="text-[10px] opacity-70">#{q.sql_query_id}</div>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-3 py-1 transition",
        active
          ? "bg-background font-semibold shadow-sm"
          : "text-muted-foreground hover:bg-background/60",
      )}
    >
      {children}
    </button>
  );
}

function Banner({
  variant,
  title,
  children,
}: {
  variant: "success" | "error" | "muted";
  title: string;
  children: React.ReactNode;
}) {
  const styles = {
    success: "border-emerald-300 bg-emerald-50 text-emerald-800",
    error: "border-rose-300 bg-rose-50 text-rose-800",
    muted: "border-border bg-muted/40 text-muted-foreground",
  } as const;
  const Icon = variant === "error" ? XCircle : variant === "success" ? CheckCircle2 : ListChecks;
  return (
    <div
      className={cn("flex items-start gap-2 rounded-md border p-2 text-xs", styles[variant])}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        <div className="font-semibold">{title}</div>
        <div>{children}</div>
      </div>
    </div>
  );
}

function PreviewTable({
  loading,
  data,
  error,
}: {
  loading: boolean;
  data: { columns: string[]; rows: unknown[][]; truncated: boolean } | undefined;
  error?: string;
}) {
  if (loading) return <p className="text-xs text-muted-foreground">실행 중…</p>;
  if (error) {
    return (
      <Banner variant="error" title="Preview 실패">
        <span className="font-mono">{error}</span>
      </Banner>
    );
  }
  if (!data) {
    return <p className="text-xs text-muted-foreground">Preview 결과 없음.</p>;
  }
  return (
    <div className="space-y-2">
      {data.truncated && (
        <p className="text-[10px] text-amber-700">
          ※ LIMIT 에서 잘렸습니다 — 결과는 sandbox 부분 결과입니다.
        </p>
      )}
      <Table>
        <Thead>
          <Tr>
            {data.columns.map((c) => (
              <Th key={c} className="font-mono">
                {c}
              </Th>
            ))}
          </Tr>
        </Thead>
        <Tbody>
          {data.rows.map((row, idx) => (
            <Tr key={idx}>
              {row.map((cell, j) => (
                <Td key={j} className="font-mono text-[11px]">
                  {cell == null ? <span className="opacity-50">NULL</span> : String(cell)}
                </Td>
              ))}
            </Tr>
          ))}
        </Tbody>
      </Table>
    </div>
  );
}
