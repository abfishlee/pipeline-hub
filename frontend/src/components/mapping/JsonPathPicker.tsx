// Phase 8.2 — Field Mapping 시각 매핑 (단순 picker).
//
// 사용자가 sample JSON 응답을 텍스트박스에 붙여넣으면 tree 생성 →
// 노드 클릭 시 source_path 가 자동 입력. 정식 drag&drop 은 Phase 9.
import { ChevronDown, ChevronRight, FileJson } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";

interface JsonNode {
  path: string;
  key: string;
  type: string;
  value: unknown;
  children?: JsonNode[];
}

function buildTree(value: unknown, path = "$", key = ""): JsonNode {
  const type = Array.isArray(value)
    ? "array"
    : value === null
      ? "null"
      : typeof value;

  const node: JsonNode = { path, key, type, value };

  if (Array.isArray(value)) {
    // sample 배열은 첫 1~3 개 요소만 노출
    node.children = value.slice(0, 3).map((v, i) =>
      buildTree(v, `${path}[${i}]`, `[${i}]`),
    );
  } else if (value && typeof value === "object") {
    node.children = Object.entries(value as Record<string, unknown>).map(
      ([k, v]) => buildTree(v, `${path}.${k}`, k),
    );
  }
  return node;
}

interface TreeNodeProps {
  node: JsonNode;
  onPick: (path: string, valueType: string) => void;
  depth: number;
}

function TreeNode({ node, onPick, depth }: TreeNodeProps) {
  const [open, setOpen] = useState(depth < 2);
  const hasChildren = !!node.children && node.children.length > 0;

  const isLeaf = !hasChildren;
  const valuePreview =
    !isLeaf
      ? ""
      : node.value === null
        ? "null"
        : node.type === "string"
          ? `"${String(node.value).slice(0, 30)}${String(node.value).length > 30 ? "..." : ""}"`
          : String(node.value);

  return (
    <div className="text-xs">
      <div
        className="flex items-center gap-1 rounded px-1 py-0.5 hover:bg-secondary"
        style={{ paddingLeft: depth * 10 + 4 }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setOpen(!open)}
            className="text-muted-foreground"
          >
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </button>
        ) : (
          <span className="w-3" />
        )}
        <button
          type="button"
          onClick={() => onPick(node.path, node.type)}
          className="flex flex-1 items-center gap-1 text-left"
          title={`경로: ${node.path}`}
        >
          <span className="font-mono font-semibold text-primary">{node.key || "$"}</span>
          <span className="text-[10px] text-muted-foreground">[{node.type}]</span>
          {valuePreview && (
            <span className="ml-1 text-[10px] text-muted-foreground">
              = {valuePreview}
            </span>
          )}
        </button>
      </div>
      {open && hasChildren && (
        <div>
          {node.children!.map((c) => (
            <TreeNode key={c.path} node={c} onPick={onPick} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

const TRANSFORM_RECOMMENDATIONS: Record<string, string[]> = {
  number: ["number.parse_decimal", "number.parse_int"],
  string: ["text.trim", "text.upper", "text.lower"],
  null: [],
  array: [],
  object: [],
};

const KEY_HINTS: Record<string, string[]> = {
  price: ["number.parse_decimal"],
  date: ["date.parse", "date.normalize_ymd"],
  ymd: ["date.normalize_ymd"],
  regday: ["date.normalize_ymd"],
  amount: ["number.parse_decimal"],
};

interface JsonPathPickerProps {
  onPick: (path: string, recommendedTransform: string | null) => void;
  initialJson?: string;
}

export function JsonPathPicker({ onPick, initialJson }: JsonPathPickerProps) {
  const [jsonText, setJsonText] = useState(
    initialJson ??
      `{\n  "items": [\n    {\n      "itemname": "사과 1.5kg",\n      "price": "12,900원",\n      "regday": "20260427"\n    }\n  ]\n}`,
  );
  const [parsed, setParsed] = useState<unknown>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    try {
      const obj = JSON.parse(jsonText);
      setParsed(obj);
      setParseError(null);
    } catch (e) {
      setParsed(null);
      setParseError((e as Error).message);
    }
  }, [jsonText]);

  const tree = useMemo(() => {
    if (parsed === null) return null;
    return buildTree(parsed);
  }, [parsed]);

  function handlePick(path: string, valueType: string) {
    // 추천 변환 함수
    const lastKey = path.split(".").pop()?.toLowerCase() ?? "";
    let rec: string | null = null;
    for (const [hint, fns] of Object.entries(KEY_HINTS)) {
      if (lastKey.includes(hint) && fns.length > 0) {
        rec = fns[0];
        break;
      }
    }
    if (!rec && TRANSFORM_RECOMMENDATIONS[valueType]) {
      const fns = TRANSFORM_RECOMMENDATIONS[valueType];
      if (fns.length > 0) rec = fns[0];
    }
    onPick(path, rec);
  }

  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex items-center gap-2 text-xs font-semibold">
          <FileJson className="h-3.5 w-3.5 text-primary" />
          Sample 응답 JSON 으로 source_path 자동 입력
        </div>
        <textarea
          className="h-32 w-full resize-none rounded-md border border-input bg-background p-2 font-mono text-[10px]"
          value={jsonText}
          onChange={(e) => setJsonText(e.target.value)}
          placeholder='{"items": [{"name": "...", "price": "..."}]}'
        />
        {parseError && (
          <p className="text-[10px] text-rose-600">JSON 파싱 오류: {parseError}</p>
        )}
        {tree && (
          <div className="max-h-48 overflow-y-auto rounded-md border border-border bg-muted/30 p-2">
            <TreeNode node={tree} onPick={handlePick} depth={0} />
          </div>
        )}
        <p className="text-[10px] text-muted-foreground">
          ※ JSON tree 의 leaf 노드 클릭 → source_path 와 변환 함수가 폼에 자동 입력.
          정식 drag&drop 은 Phase 9.
        </p>
      </CardContent>
    </Card>
  );
}
