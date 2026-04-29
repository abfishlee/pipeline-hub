// Phase 6 Wave 4 ??ETL Canvas v2 (workbench 5: ?먯궛??諛뺤뒪濡?議곕┰).
//
// ?ъ슜???쒕굹由ъ삤 (짠 13.5):
//   1. 醫뚯륫 palette ?먯꽌 13醫?v2 ?몃뱶 諛뺤뒪 ?쒕옒洹???罹붾쾭??//   2. 諛뺤뒪 ?대┃ ???곗륫 drawer ?먯꽌 *?대뼡 ?먯궛* ?ъ슜?좎? dropdown ?좏깮
//      - PUBLIC_API_FETCH ??connector dropdown
//      - MAP_FIELDS ??contract_id dropdown
//      - SQL_ASSET_TRANSFORM ??asset_code + version
//      - LOAD_TARGET ??load_policy
//      - HTTP_TRANSFORM ??provider_code
//   3. ?먯궛???놁쑝硫?"+ ???먯궛 留뚮뱾湲? 踰꾪듉 ???대떦 designer 濡??대룞 (蹂???
//   4. ?붿궡???곌껐 + ?????wf.workflow_definition 1嫄?/ wf.node_definition N媛?//   5. PUBLISH ???ㅼ?以??ㅽ뻾 (v1 ? ?숈씪 諛깆뿏??
//
// 諛깆뿏?쒕뒗 /v1/pipelines API 瑜?洹몃?濡??ъ슜 (NodeType Literal ?뺤옣?쇰줈 v2 ?몃뱶???듦낵).
import {
  addEdge,
  Background,
  type Connection,
  Controls,
  type Edge,
  MiniMap,
  type Node,
  type NodeMouseHandler,
  type OnConnect,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  FlaskConical,
  Loader2,
  Save,
  Send,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  type EdgeIn,
  type NodeIn,
  type NodeType,
  useCreateWorkflow,
  useTransitionWorkflowStatus,
  useUpdateWorkflow,
  useWorkflowDetail,
} from "@/api/pipelines";
import { CanvasPatternHint } from "@/components/canvas/CanvasPatternHint";
import { CanvasProgressBar } from "@/components/canvas/CanvasProgressBar";
import { CanvasReadinessChecklist } from "@/components/canvas/CanvasReadinessChecklist";
import {
  type DesignerNodeDataV2,
  NodeConfigPanelV2,
} from "@/components/designer/NodeConfigPanelV2";
import {
  NODE_PALETTE_V2_DRAG_MIME,
  NodePaletteV2,
} from "@/components/designer/NodePaletteV2";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type DesignerFlowNode = Node<DesignerNodeDataV2>;

const GRID_COL_GAP = 280;
const GRID_ROW_GAP = 120;
const OCCUPIED_TOLERANCE = 36;

// v2 ?몃뱶 prefix ???좉퇋 ?몃뱶 key ?먮룞 ?앹꽦??
const V2_KEY_PREFIX: Partial<Record<NodeType, string>> = {
  SOURCE_DATA: "src",
  PUBLIC_API_FETCH: "fetch_api",
  OCR_TRANSFORM: "ocr",
  CRAWL_FETCH: "crawl",
  MAP_FIELDS: "map",
  SQL_INLINE_TRANSFORM: "sql_inline",
  SQL_ASSET_TRANSFORM: "sql_asset",
  PYTHON_MODEL_TRANSFORM: "python_model",
  HTTP_TRANSFORM: "http",
  FUNCTION_TRANSFORM: "fn",
  STANDARDIZE: "stdz",
  DEDUP: "dedup",
  DQ_CHECK: "dq",
  LOAD_TARGET: "load",
  NOTIFY: "notify",
};

function defaultNodeKey(type: NodeType, existingKeys: Set<string>): string {
  const prefix = V2_KEY_PREFIX[type] ?? type.toLowerCase();
  let i = 1;
  while (existingKeys.has(`${prefix}_${i}`)) i += 1;
  return `${prefix}_${i}`;
}

function snapToGrid(value: number, base: number, gap: number): number {
  return base + Math.round((value - base) / gap) * gap;
}

function isOccupied(
  position: { x: number; y: number },
  nodes: DesignerFlowNode[],
): boolean {
  return nodes.some(
    (n) =>
      Math.abs(n.position.x - position.x) < OCCUPIED_TOLERANCE &&
      Math.abs(n.position.y - position.y) < OCCUPIED_TOLERANCE,
  );
}

function firstFreeSlot(
  position: { x: number; y: number },
  nodes: DesignerFlowNode[],
): { x: number; y: number } {
  let next = { ...position };
  while (isOccupied(next, nodes)) {
    next = { x: next.x, y: next.y + GRID_ROW_GAP };
  }
  return next;
}

function alignedDropPosition(
  raw: { x: number; y: number },
  nodes: DesignerFlowNode[],
): { x: number; y: number } {
  if (nodes.length === 0) {
    return {
      x: Math.round(raw.x / GRID_COL_GAP) * GRID_COL_GAP,
      y: Math.round(raw.y / GRID_ROW_GAP) * GRID_ROW_GAP,
    };
  }
  const base = nodes[0].position;
  const snapped = {
    x: snapToGrid(raw.x, base.x, GRID_COL_GAP),
    y: snapToGrid(raw.y, base.y, GRID_ROW_GAP),
  };
  return firstFreeSlot(snapped, nodes);
}

function nextSequentialPosition(
  nodes: DesignerFlowNode[],
  selectedId: string | null,
  fallback: { x: number; y: number },
): { x: number; y: number } {
  if (nodes.length === 0) return alignedDropPosition(fallback, nodes);
  const selected = selectedId ? nodes.find((n) => n.id === selectedId) : null;
  const anchor = selected ?? nodes[nodes.length - 1];
  return firstFreeSlot(
    { x: anchor.position.x + GRID_COL_GAP, y: anchor.position.y },
    nodes,
  );
}

function makeFlowNode(
  type: NodeType,
  position: { x: number; y: number },
  existingKeys: Set<string>,
): DesignerFlowNode {
  const node_key = defaultNodeKey(type, existingKeys);
  const config_json =
    type === "PYTHON_MODEL_TRANSFORM"
      ? {
          code: [
            "rows = read_rows(limit=1000)",
            "result_rows = []",
            "for row in rows:",
            "    payload = row.get('payload') or row",
            "    result_rows.append({",
            "        'store_name': payload.get('store_name') or payload.get('storeName') or payload.get('점포명'),",
            "        'item_name': payload.get('item') or payload.get('itemName') or payload.get('품목'),",
            "        'regular_price': re.sub(r'[^0-9.]', '', str(payload.get('regular_price') or payload.get('regularPrice') or payload.get('정상가') or '')) or None,",
            "    })",
          ].join("\n"),
          model_category: "TRANSFORM",
          model_version: 1,
        }
      : {};
  const data: DesignerNodeDataV2 = {
    node_key,
    node_type: type,
    config_json,
    position_x: position.x,
    position_y: position.y,
  };
  return { id: node_key, position, data, type: "default" };
}

function DesignerInner() {
  const params = useParams<{ workflowId?: string }>();
  const editingWorkflowId = params.workflowId ? Number(params.workflowId) : null;
  const navigate = useNavigate();
  const reactFlow = useReactFlow();

  const detail = useWorkflowDetail(editingWorkflowId);
  const create = useCreateWorkflow();
  const update = useUpdateWorkflow();
  const transition = useTransitionWorkflowStatus();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [nodes, setNodes, onNodesChange] = useNodesState<DesignerFlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hydrated, setHydrated] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // hydrate from detail.
  useEffect(() => {
    if (!detail.data || hydrated) return;
    const wf = detail.data;
    setName(wf.name);
    setDescription(wf.description ?? "");
    const nodeKeyById = new Map<number, string>();
    const flowNodes: DesignerFlowNode[] = wf.nodes.map((n) => {
      nodeKeyById.set(n.node_id, n.node_key);
      return {
        id: n.node_key,
        position: { x: n.position_x, y: n.position_y },
        data: {
          node_key: n.node_key,
          node_type: n.node_type,
          config_json: n.config_json,
          position_x: n.position_x,
          position_y: n.position_y,
        },
        type: "default",
      };
    });
    const flowEdges: Edge[] = wf.edges
      .map((e, idx) => {
        const src = nodeKeyById.get(e.from_node_id);
        const tgt = nodeKeyById.get(e.to_node_id);
        if (!src || !tgt) return null;
        return {
          id: `e_${idx}_${src}_${tgt}`,
          source: src,
          target: tgt,
        } satisfies Edge;
      })
      .filter((e): e is Edge => e !== null);
    setNodes(flowNodes);
    setEdges(flowEdges);
    setHydrated(true);
  }, [detail.data, hydrated, setNodes, setEdges]);

  const existingKeys = useMemo(
    () => new Set(nodes.map((n) => n.data.node_key)),
    [nodes],
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData(
        NODE_PALETTE_V2_DRAG_MIME,
      ) as NodeType | "";
      if (!type) return;
      const bounds = wrapperRef.current?.getBoundingClientRect();
      if (!bounds) return;
      const position = reactFlow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const next = makeFlowNode(type, alignedDropPosition(position, nodes), existingKeys);
      setNodes((curr) => [...curr, next]);
      setSelectedId(next.id);
    },
    [reactFlow, nodes, existingKeys, setNodes],
  );

  const handlePaletteAdd = useCallback(
    (type: NodeType) => {
      const center = reactFlow.screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      });
      const next = makeFlowNode(
        type,
        nextSequentialPosition(nodes, selectedId, center),
        existingKeys,
      );
      setNodes((curr) => [...curr, next]);
      setSelectedId(next.id);
    },
    [reactFlow, nodes, selectedId, existingKeys, setNodes],
  );

  const onConnect: OnConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      if (conn.source === conn.target) {
        toast.error("?먭린 ?먯떊怨쇰뒗 ?곌껐?????놁뒿?덈떎.");
        return;
      }
      setEdges((curr) =>
        addEdge(
          {
            ...conn,
            id: `e_${conn.source}_${conn.target}_${Date.now()}`,
          },
          curr,
        ),
      );
    },
    [setEdges],
  );

  const onNodeClick: NodeMouseHandler = useCallback((_, node) => {
    setSelectedId(node.id);
  }, []);

  useEffect(() => {
    setNodes((curr) =>
      curr.map((n) =>
        n.position.x === n.data.position_x && n.position.y === n.data.position_y
          ? n
          : {
              ...n,
              data: {
                ...n.data,
                position_x: n.position.x,
                position_y: n.position.y,
              },
            },
      ),
    );
  }, [nodes.length, setNodes]);

  const selected = useMemo(
    () => nodes.find((n) => n.id === selectedId)?.data ?? null,
    [nodes, selectedId],
  );

  const updateSelected = useCallback(
    (next: DesignerNodeDataV2) => {
      setNodes((curr) =>
        curr.map((n) => {
          if (n.id !== selectedId) return n;
          const newId = next.node_key;
          const oldId = n.id;
          if (newId !== oldId) {
            setEdges((es) =>
              es.map((e) => ({
                ...e,
                source: e.source === oldId ? newId : e.source,
                target: e.target === oldId ? newId : e.target,
              })),
            );
            setSelectedId(newId);
          }
          return {
            ...n,
            id: newId,
            position: { x: next.position_x, y: next.position_y },
            data: next,
          };
        }),
      );
    },
    [selectedId, setNodes, setEdges],
  );

  const deleteSelected = useCallback(() => {
    if (!selectedId) return;
    setNodes((curr) => curr.filter((n) => n.id !== selectedId));
    setEdges((curr) =>
      curr.filter((e) => e.source !== selectedId && e.target !== selectedId),
    );
    setSelectedId(null);
  }, [selectedId, setNodes, setEdges]);

  const buildPayload = useCallback(() => {
    const nodeIns: NodeIn[] = nodes.map((n) => ({
      node_key: n.data.node_key,
      node_type: n.data.node_type,
      config_json: n.data.config_json,
      position_x: n.position.x,
      position_y: n.position.y,
    }));
    const edgeIns: EdgeIn[] = edges.map((e) => ({
      from_node_key: e.source,
      to_node_key: e.target,
    }));
    return {
      name,
      description: description || null,
      nodes: nodeIns,
      edges: edgeIns,
    };
  }, [nodes, edges, name, description]);

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error("workflow name을 입력해 주세요.");
      return;
    }
    if (nodes.length === 0) {
      toast.error("최소 1개 노드가 필요합니다.");
      return;
    }
    const payload = buildPayload();
    try {
      if (editingWorkflowId) {
        await update.mutateAsync({
          workflowId: editingWorkflowId,
          body: payload,
        });
        toast.success("저장 완료");
      } else {
        const created = await create.mutateAsync(payload);
        toast.success(`생성 완료 (workflow_id=${created.workflow_id})`);
        navigate(`/v2/pipelines/designer/${created.workflow_id}`, {
          replace: true,
        });
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "저장 실패");
    }
  };

  const handlePublish = async () => {
    if (!editingWorkflowId) {
      toast.error("癒쇱? ??ν빐 二쇱꽭??");
      return;
    }
    if (detail.data?.status !== "DRAFT") {
      toast.error(`현재 상태=${detail.data?.status}; DRAFT만 PUBLISH할 수 있습니다.`);
      return;
    }
    try {
      const result = await transition.mutateAsync({
        workflowId: editingWorkflowId,
        status: "PUBLISHED",
      });
      const pub = result.published_workflow;
      const rel = result.release;
      if (pub && rel) {
        toast.success(`v${pub.version} 諛고룷 ?꾨즺 (release #${rel.release_id})`);
        navigate(`/v2/pipelines/designer/${pub.workflow_id}`);
      } else {
        toast.success("諛고룷 ?꾨즺");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "?꾪솚 ?ㅽ뙣");
    }
  };

  const status = detail.data?.status ?? "DRAFT";
  const isReadonly = !!editingWorkflowId && status !== "DRAFT";

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col gap-3">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-3 text-sm">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="workflow name"
            disabled={isReadonly}
            className="h-9 w-64"
          />
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="설명 (선택)"
            disabled={isReadonly}
            className="h-9 flex-1 min-w-[180px]"
          />
          {editingWorkflowId && (
            <>
              <span className="text-xs text-muted-foreground">
                #{editingWorkflowId}
              </span>
              <Badge variant={status === "PUBLISHED" ? "default" : "muted"}>
                {status}
              </Badge>
            </>
          )}
          <div className="ml-auto flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={handleSave}
              disabled={isReadonly || create.isPending || update.isPending}
            >
              {create.isPending || update.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              저장
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (!editingWorkflowId) {
                  toast.error("癒쇱? ??ν빐 二쇱꽭??");
                  return;
                }
                navigate(`/v2/dryrun/workflow/${editingWorkflowId}?auto=1`);
              }}
              disabled={!editingWorkflowId}
            >
              <FlaskConical className="h-3 w-3" />
              Dry-run
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={handlePublish}
              disabled={
                !editingWorkflowId ||
                status !== "DRAFT" ||
                transition.isPending
              }
            >
              <Send className="h-3 w-3" />
              PUBLISH
            </Button>
            <Button
              size="sm"
              onClick={() => navigate("/pipelines/runs")}
              disabled={!editingWorkflowId}
            >
              Jobs & Runs
            </Button>
          </div>
          {isReadonly && (
            <p className="basis-full text-xs text-amber-700">
              ??{status} ?뚰겕?뚮줈???몄쭛?????놁뒿?덈떎. ??踰꾩쟾???앹꽦??二쇱꽭??
            </p>
          )}

          {editingWorkflowId && status === "PUBLISHED" && (
            <p className="basis-full border-t border-border pt-3 text-xs text-muted-foreground">
              실행 주기, 즉시 실행, 모니터링은 Jobs & Runs 화면에서 관리합니다.
            </p>
          )}
        </CardContent>
      </Card>

      <CanvasProgressBar nodeTypes={nodes.map((n) => n.data.node_type)} />

      {/* Phase 8.6 ???좉퇋 ?ъ슜??媛?대뱶 (?몃뱶 0媛??쒖젏??媛???좎슜) */}
      {nodes.length === 0 && <CanvasPatternHint />}

      {nodes.length > 0 && (
        <CanvasReadinessChecklist nodes={nodes} edges={edges} />
      )}

      <div className="flex min-h-[460px] flex-1 overflow-hidden rounded-lg border border-border bg-background">
        <NodePaletteV2 onAdd={handlePaletteAdd} />
        <div
          ref={wrapperRef}
          className="flex-1"
          onDragOver={onDragOver}
          onDrop={onDrop}
        >
          <ReactFlow
            className="h-full min-h-[460px]"
            nodes={nodes.map((n) => ({
              ...n,
              data: {
                ...n.data,
                label: `${n.data.node_key}\n[${n.data.node_type}]`,
              },
              selected: n.id === selectedId,
            }))}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={() => setSelectedId(null)}
            fitView
            proOptions={{ hideAttribution: true }}
            defaultEdgeOptions={{ type: "smoothstep" }}
            nodesDraggable={!isReadonly}
            nodesConnectable={!isReadonly}
            elementsSelectable
          >
            <Background gap={16} />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        <NodeConfigPanelV2
          selected={selected}
          onChange={updateSelected}
          onDelete={isReadonly ? undefined : deleteSelected}
        />
      </div>
    </div>
  );
}

export function EtlCanvasV2() {
  return (
    <ReactFlowProvider>
      <DesignerInner />
    </ReactFlowProvider>
  );
}
