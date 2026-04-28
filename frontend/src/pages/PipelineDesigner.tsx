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
import { Loader2, Save, Send } from "lucide-react";
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
import {
  NODE_PALETTE_DRAG_MIME,
  NodePalette,
} from "@/components/designer/NodePalette";
import {
  type DesignerNodeData,
  NodeConfigPanel,
} from "@/components/designer/NodeConfigPanel";
import { SqlEditor } from "@/components/designer/SqlEditor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type DesignerFlowNode = Node<DesignerNodeData>;

// v1 ?몃뱶 7醫낅쭔 紐낆떆 ??v2 ??蹂꾨룄 EtlCanvasV2 ?섏씠吏?먯꽌 泥섎━.
const NEXT_KEY_PREFIX: Partial<Record<NodeType, string>> = {
  NOOP: "noop",
  SOURCE_API: "src_api",
  SQL_TRANSFORM: "sql",
  DEDUP: "dedup",
  DQ_CHECK: "dq",
  LOAD_MASTER: "load",
  NOTIFY: "notify",
};

function defaultNodeKey(type: NodeType, existingKeys: Set<string>): string {
  const prefix = NEXT_KEY_PREFIX[type] ?? type.toLowerCase();
  let i = 1;
  while (existingKeys.has(`${prefix}_${i}`)) i += 1;
  return `${prefix}_${i}`;
}

function makeFlowNode(
  type: NodeType,
  position: { x: number; y: number },
  existingKeys: Set<string>,
  configOverride?: Record<string, unknown>,
): DesignerFlowNode {
  const node_key = defaultNodeKey(type, existingKeys);
  const data: DesignerNodeData = {
    node_key,
    node_type: type,
    config_json: configOverride ?? {},
    position_x: position.x,
    position_y: position.y,
  };
  return {
    id: node_key, // node_key 瑜?React Flow id 濡?吏곸젒 ?ъ슜 ???좉퇋/湲곗〈 ?듯빀.
    position,
    data,
    type: "default",
  };
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

  // 湲곗〈 ?뚰겕?뚮줈 ?곸꽭 ??React Flow ?곹깭濡?hydrate (1??.
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

  // ---- Drag & Drop from palette ----------------------------------------
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData(
        NODE_PALETTE_DRAG_MIME,
      ) as NodeType | "";
      if (!type) return;
      const bounds = wrapperRef.current?.getBoundingClientRect();
      if (!bounds) return;
      const position = reactFlow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const next = makeFlowNode(type, position, existingKeys);
      setNodes((curr) => [...curr, next]);
      setSelectedId(next.id);
    },
    [reactFlow, existingKeys, setNodes],
  );

  // ---- Add via double-click (palette ??center) -------------------------
  const handlePaletteAdd = useCallback(
    (type: NodeType) => {
      const center = reactFlow.screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      });
      const next = makeFlowNode(type, center, existingKeys);
      setNodes((curr) => [...curr, next]);
      setSelectedId(next.id);
    },
    [reactFlow, existingKeys, setNodes],
  );

  // ---- Edge connect ----------------------------------------------------
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

  // ---- Node click ??select --------------------------------------------
  const onNodeClick: NodeMouseHandler = useCallback((_, node) => {
    setSelectedId(node.id);
  }, []);

  // ---- Position changes ??sync into data.position_{x,y} ---------------
  // React Flow ??onNodesChange 媛 position ???낅뜲?댄듃?섏?留??곕━ data ??媛숈씠 留욎떠????????뺥솗.
  useEffect(() => {
    setNodes((curr) =>
      curr.map((n) =>
        n.position.x === n.data.position_x && n.position.y === n.data.position_y
          ? n
          : {
              ...n,
              data: { ...n.data, position_x: n.position.x, position_y: n.position.y },
            },
      ),
    );
  }, [nodes.length, setNodes]);

  // ---- Selected node mutations ----------------------------------------
  const selected = useMemo(
    () => nodes.find((n) => n.id === selectedId)?.data ?? null,
    [nodes, selectedId],
  );

  const updateSelected = useCallback(
    (next: DesignerNodeData) => {
      setNodes((curr) =>
        curr.map((n) => {
          if (n.id !== selectedId) return n;
          // node_key 媛 諛붾뚮㈃ React Flow id ??諛붾뚭퀬, ?곌껐??edge ???щ씪?고똿 ?꾩슂.
          const newId = next.node_key;
          const oldId = n.id;
          if (newId !== oldId) {
            // edge source/target ?대쫫 媛깆떊.
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

  // ---- Save ------------------------------------------------------------
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
    return { name, description: description || null, nodes: nodeIns, edges: edgeIns };
  }, [nodes, edges, name, description]);

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error("workflow name ???낅젰??二쇱꽭??");
      return;
    }
    if (nodes.length === 0) {
      toast.error("理쒖냼 1媛??몃뱶媛 ?꾩슂?⑸땲??");
      return;
    }
    const payload = buildPayload();
    try {
      if (editingWorkflowId) {
        await update.mutateAsync({
          workflowId: editingWorkflowId,
          body: payload,
        });
        toast.success("????꾨즺");
      } else {
        const created = await create.mutateAsync(payload);
        toast.success(`?앹꽦 ?꾨즺 (workflow_id=${created.workflow_id})`);
        navigate(`/pipelines/designer/${created.workflow_id}`, { replace: true });
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "????ㅽ뙣");
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
      // Phase 3.2.6: ?묐떟????PUBLISHED ?뚰겕?뚮줈 + release ?뺣낫 ?숇큺.
      const result = await transition.mutateAsync({
        workflowId: editingWorkflowId,
        status: "PUBLISHED",
      });
      const pub = result.published_workflow;
      const rel = result.release;
      if (pub && rel) {
        toast.success(`v${pub.version} 諛고룷 ?꾨즺 (release #${rel.release_id})`);
        // ??PUBLISHED ?뚰겕?뚮줈 ?붾㈃?쇰줈 ?대룞 ???ъ슜?먭? 洹??꾩뿉???ㅽ뻾 媛??
        navigate(`/pipelines/designer/${pub.workflow_id}`);
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
    <div className="flex h-full flex-col gap-3">
      {/* Toolbar */}
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
            placeholder="?ㅻ챸 (?좏깮)"
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
              {(create.isPending || update.isPending) ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              ???            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={handlePublish}
              disabled={!editingWorkflowId || status !== "DRAFT" || transition.isPending}
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

      {/* Three-pane editor */}
      <div className="flex flex-1 overflow-hidden rounded-lg border border-border bg-background">
        <NodePalette onAdd={handlePaletteAdd} />
        <div ref={wrapperRef} className="flex-1" onDragOver={onDragOver} onDrop={onDrop}>
          <ReactFlow
            nodes={nodes.map((n) => ({
              ...n,
              data: { ...n.data, label: `${n.data.node_key}\n[${n.data.node_type}]` },
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
        <NodeConfigPanel
          selected={selected}
          onChange={updateSelected}
          onDelete={isReadonly ? undefined : deleteSelected}
        />
      </div>

      {/* SQL Studio (always visible ??useful even when no SQL_TRANSFORM is selected) */}
      <SqlEditor
        initialSql={
          selected?.node_type === "SQL_TRANSFORM"
            ? String(selected.config_json?.sql ?? "")
            : ""
        }
        onValidated={(sql) => {
          if (selected?.node_type === "SQL_TRANSFORM") {
            updateSelected({
              ...selected,
              config_json: { ...selected.config_json, sql },
            });
            toast.success("SQL ???좏깮???몃뱶 config_json.sql ??諛섏쁺?섏뿀?듬땲??");
          }
        }}
      />
    </div>
  );
}

export function PipelineDesigner() {
  return (
    <ReactFlowProvider>
      <DesignerInner />
    </ReactFlowProvider>
  );
}
