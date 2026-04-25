import { useEffect, useMemo, useState } from "react";
import type { NodeType } from "@/api/pipelines";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

/**
 * 디자이너 캔버스의 노드 도메인 데이터.
 *
 * `[k: string]: unknown` 인덱스 시그니처는 React Flow 12 의 `Node<TData>` generic 이
 * `data extends Record<string, unknown>` 을 강제하기 때문이다 (PipelineDesigner 에서
 * 이 타입을 React Flow Node.data 로 직접 사용).
 */
export interface DesignerNodeData {
  node_key: string;
  node_type: NodeType;
  config_json: Record<string, unknown>;
  position_x: number;
  position_y: number;
  [key: string]: unknown;
}

interface Props {
  selected: DesignerNodeData | null;
  onChange: (next: DesignerNodeData) => void;
  onDelete?: () => void;
}

// 노드 타입별 config_json 힌트 — 사용자 가이드용. 실제 검증은 백엔드 NodeExecutor.
const CONFIG_HINTS: Record<NodeType, string> = {
  NOOP: '{}  // 옵션 없음',
  SOURCE_API: '{\n  "source_id": 1,\n  "limit": 100\n}',
  SQL_TRANSFORM: '{\n  "sql": "SELECT ... FROM stg.foo",\n  "target_table": "stg.bar"\n}',
  DEDUP: '{\n  "key_columns": ["sku", "captured_at"]\n}',
  DQ_CHECK: '{\n  "rules": [\n    { "type": "row_count_min", "value": 1 }\n  ]\n}',
  LOAD_MASTER: '{\n  "source_table": "stg.bar",\n  "target_table": "mart.product_price",\n  "key_columns": ["product_id", "captured_at"]\n}',
  NOTIFY: '{\n  "channel": "slack",\n  "template": "pipeline_done"\n}',
};

export function NodeConfigPanel({ selected, onChange, onDelete }: Props) {
  const [keyDraft, setKeyDraft] = useState("");
  const [jsonDraft, setJsonDraft] = useState("{}");
  const [jsonError, setJsonError] = useState<string | null>(null);

  // 선택된 노드가 바뀌면 draft 동기화.
  useEffect(() => {
    if (!selected) {
      setKeyDraft("");
      setJsonDraft("{}");
      setJsonError(null);
      return;
    }
    setKeyDraft(selected.node_key);
    setJsonDraft(JSON.stringify(selected.config_json ?? {}, null, 2));
    setJsonError(null);
  }, [selected]);

  const hint = useMemo(
    () => (selected ? CONFIG_HINTS[selected.node_type] : ""),
    [selected],
  );

  if (!selected) {
    return (
      <aside className="flex w-80 shrink-0 flex-col border-l border-border bg-background p-3 text-xs text-muted-foreground">
        <div className="mb-2 text-xs font-semibold uppercase">노드 설정</div>
        <p>좌측 캔버스에서 노드를 선택하면 설정을 편집할 수 있습니다.</p>
      </aside>
    );
  }

  const commitKey = () => {
    if (keyDraft && keyDraft !== selected.node_key) {
      onChange({ ...selected, node_key: keyDraft });
    }
  };

  const commitJson = () => {
    try {
      const parsed = jsonDraft.trim() ? JSON.parse(jsonDraft) : {};
      if (typeof parsed !== "object" || parsed == null || Array.isArray(parsed)) {
        setJsonError("config_json 은 object 여야 합니다.");
        return;
      }
      setJsonError(null);
      onChange({ ...selected, config_json: parsed as Record<string, unknown> });
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "JSON 파싱 실패");
    }
  };

  return (
    <aside className="flex w-80 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border bg-background p-3">
      <div className="text-xs font-semibold uppercase text-muted-foreground">
        노드 설정
      </div>

      <Card>
        <CardContent className="space-y-3 p-3 text-xs">
          <div>
            <label className="mb-1 block font-semibold">node_type</label>
            <div className="rounded-md border border-input bg-muted/40 px-3 py-2 font-mono">
              {selected.node_type}
            </div>
          </div>

          <div>
            <label className="mb-1 block font-semibold">node_key</label>
            <Input
              value={keyDraft}
              onChange={(e) => setKeyDraft(e.target.value)}
              onBlur={commitKey}
              placeholder="예: extract_prices"
              className="h-9 text-xs font-mono"
            />
            <p className="mt-1 text-[10px] text-muted-foreground">
              워크플로 안에서 유일한 식별자. blur 시 반영.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block font-semibold">x</label>
              <Input
                type="number"
                value={selected.position_x}
                onChange={(e) =>
                  onChange({ ...selected, position_x: Number(e.target.value) })
                }
                className="h-9 text-xs"
              />
            </div>
            <div>
              <label className="mb-1 block font-semibold">y</label>
              <Input
                type="number"
                value={selected.position_y}
                onChange={(e) =>
                  onChange({ ...selected, position_y: Number(e.target.value) })
                }
                className="h-9 text-xs"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-2 p-3 text-xs">
          <label className="block font-semibold">config_json</label>
          <textarea
            value={jsonDraft}
            onChange={(e) => setJsonDraft(e.target.value)}
            onBlur={commitJson}
            spellCheck={false}
            className="h-56 w-full resize-none rounded-md border border-input bg-background p-2 font-mono text-[11px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {jsonError && (
            <p className="text-[11px] text-rose-600">파싱 오류: {jsonError}</p>
          )}
          <details className="text-[10px] text-muted-foreground">
            <summary className="cursor-pointer">힌트 ({selected.node_type})</summary>
            <pre className="mt-1 whitespace-pre-wrap rounded bg-muted/60 p-2 font-mono">
              {hint}
            </pre>
          </details>
          <p className="text-[10px] text-muted-foreground">
            ※ 백엔드 NodeExecutor 가 최종 검증. 잘못된 키는 실행 시 FAILED.
          </p>
        </CardContent>
      </Card>

      {onDelete && (
        <Button variant="destructive" size="sm" onClick={onDelete}>
          노드 삭제
        </Button>
      )}
    </aside>
  );
}
