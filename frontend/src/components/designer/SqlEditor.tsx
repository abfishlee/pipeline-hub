import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import { useValidateSql } from "@/api/sql_studio";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

interface Props {
  /** 외부(NodeConfigPanel)에서 SQL 을 주입할 때만 사용. */
  initialSql?: string;
  /** 검증 통과한 SQL 을 호출자(예: SQL_TRANSFORM config_json.sql) 로 전달. */
  onValidated?: (sql: string, referencedTables: string[]) => void;
}

/**
 * SQL Studio dry-run validate UI.
 *
 * Phase 3.2.4 한정 — sqlglot AST 정적 검증만. 실제 sandbox 실행은 후속 sub-phase.
 * 백엔드는 200 + valid=false 로 위반을 돌려주므로 mutation.error 가 아니라
 * data.valid 를 봐야 한다.
 */
export function SqlEditor({ initialSql = "", onValidated }: Props) {
  const [sql, setSql] = useState(initialSql);
  const validate = useValidateSql();
  const result = validate.data;

  const handleValidate = () => {
    if (!sql.trim()) return;
    validate.mutate(sql, {
      onSuccess: (data) => {
        if (data.valid && onValidated) {
          onValidated(sql, data.referenced_tables);
        }
      },
    });
  };

  return (
    <Card>
      <CardContent className="space-y-3 p-3">
        <div className="flex items-center justify-between">
          <h4 className="text-sm font-semibold">SQL Studio (dry-run validate)</h4>
          <Button
            size="sm"
            onClick={handleValidate}
            disabled={validate.isPending || !sql.trim()}
          >
            {validate.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
            검증
          </Button>
        </div>

        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          spellCheck={false}
          placeholder="SELECT product_id, price FROM stg.daily_prices WHERE captured_at >= now() - interval '1 day'"
          className="h-44 w-full resize-y rounded-md border border-input bg-background p-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />

        {validate.isError && (
          <div className="flex items-start gap-2 rounded-md border border-rose-300 bg-rose-50 p-2 text-xs text-rose-700">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-semibold">네트워크 오류</div>
              <div>{(validate.error as Error)?.message ?? "알 수 없는 오류"}</div>
            </div>
          </div>
        )}

        {result && !result.valid && (
          <div className="flex items-start gap-2 rounded-md border border-rose-300 bg-rose-50 p-2 text-xs text-rose-700">
            <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-semibold">검증 실패</div>
              <div className="font-mono">{result.error ?? "원인 미상"}</div>
            </div>
          </div>
        )}

        {result?.valid && (
          <div className="flex items-start gap-2 rounded-md border border-emerald-300 bg-emerald-50 p-2 text-xs text-emerald-700">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-semibold">통과</div>
              {result.referenced_tables.length > 0 && (
                <div className="mt-1 font-mono">
                  참조 테이블: {result.referenced_tables.join(", ")}
                </div>
              )}
            </div>
          </div>
        )}

        <p className="text-[10px] text-muted-foreground">
          ※ 허용 스키마: <code>mart</code>, <code>stg</code>, <code>wf</code>.
          SELECT/UNION/CTE 만. DROP/INSERT/COPY/pg_* 함수는 거부.
        </p>
      </CardContent>
    </Card>
  );
}
