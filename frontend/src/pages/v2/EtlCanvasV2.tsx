// Phase 6 Wave 4 — ETL Canvas v2 (workbench 5: 자산을 박스로 조립).
//
// 사용자 시나리오 (§ 13.5):
//   1. 좌측 palette 에서 13종 v2 노드 박스 드래그 → 캔버스
//   2. 박스 클릭 → 우측 drawer 에서 *어떤 자산* 사용할지 dropdown 선택
//      - PUBLIC_API_FETCH → connector dropdown
//      - MAP_FIELDS → contract_id dropdown
//      - SQL_ASSET_TRANSFORM → asset_code + version
//      - LOAD_TARGET → load_policy
//      - HTTP_TRANSFORM → provider_code
//   3. 자산이 없으면 "+ 새 자산 만들기" 버튼 → 해당 designer 로 이동 (별 탭)
//   4. 화살표 연결 + 저장 → wf.workflow_definition 1건 / wf.node_definition N개
//   5. PUBLISH → 스케줄/실행 (v1 와 동일 백엔드)
//
// 백엔드는 /v1/pipelines API 를 그대로 사용 (NodeType Literal 확장으로 v2 노드도 통과).
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
  CalendarRange,
  Clock,
  Loader2,
  PlayCircle,
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
  useBackfill,
  useCreateWorkflow,
  useTransitionWorkflowStatus,
  useTriggerRun,
  useUpdateSchedule,
  useUpdateWorkflow,
  useWorkflowDetail,
} from "@/api/pipelines";
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

// v2 노드 prefix — 신규 노드 key 자동 생성용.
const V2_KEY_PREFIX: Partial<Record<NodeType, string>> = {
  SOURCE_DATA: "src",
  PUBLIC_API_FETCH: "fetch_api",
  OCR_TRANSFORM: "ocr",
  CRAWL_FETCH: "crawl",
  MAP_FIELDS: "map",
  SQL_INLINE_TRANSFORM: "sql_inline",
  SQL_ASSET_TRANSFORM: "sql_asset",
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

function makeFlowNode(
  type: NodeType,
  position: { x: number; y: number },
  existingKeys: Set<string>,
): DesignerFlowNode {
  const node_key = defaultNodeKey(type, existingKeys);
  const data: DesignerNodeDataV2 = {
    node_key,
    node_type: type,
    config_json: {},
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
  const trigger = useTriggerRun();
  const updateSchedule = useUpdateSchedule();
  const backfill = useBackfill();

  const [showBackfill, setShowBackfill] = useState(false);
  const [backfillStart, setBackfillStart] = useState("");
  const [backfillEnd, setBackfillEnd] = useState("");
  const [cronDraft, setCronDraft] = useState("");
  const [scheduleEnabledDraft, setScheduleEnabledDraft] = useState(false);

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
    setCronDraft(wf.schedule_cron ?? "");
    setScheduleEnabledDraft(wf.schedule_enabled);
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
      const next = makeFlowNode(type, position, existingKeys);
      setNodes((curr) => [...curr, next]);
      setSelectedId(next.id);
    },
    [reactFlow, existingKeys, setNodes],
  );

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

  const onConnect: OnConnect = useCallback(
    (conn: Connection) => {
      if (!conn.source || !conn.target) return;
      if (conn.source === conn.target) {
        toast.error("자기 자신과는 연결할 수 없습니다.");
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
      toast.error("workflow name 을 입력해 주세요.");
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
      toast.error("먼저 저장해 주세요.");
      return;
    }
    if (detail.data?.status !== "DRAFT") {
      toast.error(`현재 상태=${detail.data?.status} — DRAFT 만 PUBLISH 가능`);
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
        toast.success(`v${pub.version} 배포 완료 (release #${rel.release_id})`);
        navigate(`/v2/pipelines/designer/${pub.workflow_id}`);
      } else {
        toast.success("배포 완료");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "전환 실패");
    }
  };

  const handleSaveSchedule = async () => {
    if (!editingWorkflowId) return;
    try {
      await updateSchedule.mutateAsync({
        workflowId: editingWorkflowId,
        cron: cronDraft.trim() || null,
        enabled: scheduleEnabledDraft && !!cronDraft.trim(),
      });
      toast.success("스케줄 저장됨");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "스케줄 저장 실패");
    }
  };

  const handleBackfill = async () => {
    if (!editingWorkflowId) return;
    if (!backfillStart || !backfillEnd) {
      toast.error("시작/종료 날짜를 선택해 주세요.");
      return;
    }
    try {
      const res = await backfill.mutateAsync({
        workflowId: editingWorkflowId,
        start_date: backfillStart,
        end_date: backfillEnd,
      });
      toast.success(`Backfill 적재됨 — run ${res.pipeline_run_ids.length}개`);
      setShowBackfill(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Backfill 실패");
    }
  };

  const handleRun = async () => {
    if (!editingWorkflowId) return;
    if (detail.data?.status !== "PUBLISHED") {
      toast.error("PUBLISHED 워크플로만 실행 가능합니다.");
      return;
    }
    try {
      const run = await trigger.mutateAsync(editingWorkflowId);
      toast.success(`실행 트리거됨 (run_id=${run.pipeline_run_id})`);
      navigate(`/pipelines/runs/${run.pipeline_run_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "실행 실패");
    }
  };

  const status = detail.data?.status ?? "DRAFT";
  const isReadonly = !!editingWorkflowId && status !== "DRAFT";

  return (
    <div className="flex h-full flex-col gap-3">
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
              onClick={handleRun}
              disabled={status !== "PUBLISHED" || trigger.isPending}
            >
              <PlayCircle className="h-3 w-3" />
              실행
            </Button>
          </div>
          {isReadonly && (
            <p className="basis-full text-xs text-amber-700">
              ※ {status} 워크플로는 편집할 수 없습니다. 새 버전을 생성해 주세요.
            </p>
          )}

          {editingWorkflowId && status === "PUBLISHED" && (
            <div className="basis-full flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs">
              <Clock className="h-3 w-3 text-muted-foreground" />
              <span className="text-muted-foreground">cron (UTC, 5필드):</span>
              <Input
                value={cronDraft}
                onChange={(e) => setCronDraft(e.target.value)}
                placeholder="0 5 * * *"
                className="h-8 w-40 font-mono text-xs"
              />
              <label className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={scheduleEnabledDraft}
                  onChange={(e) => setScheduleEnabledDraft(e.target.checked)}
                  disabled={!cronDraft.trim()}
                />
                <span>활성</span>
              </label>
              <Button
                size="sm"
                variant="outline"
                onClick={handleSaveSchedule}
                disabled={updateSchedule.isPending}
              >
                스케줄 저장
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowBackfill((v) => !v)}
              >
                <CalendarRange className="h-3 w-3" />
                Backfill
              </Button>
              {detail.data?.schedule_cron && (
                <span className="text-muted-foreground">
                  현재: <code>{detail.data.schedule_cron}</code> ·{" "}
                  {detail.data.schedule_enabled ? "ON" : "OFF"}
                </span>
              )}
            </div>
          )}

          {showBackfill && editingWorkflowId && status === "PUBLISHED" && (
            <div className="basis-full flex flex-wrap items-center gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs">
              <span className="text-amber-800">
                Backfill — 시작/종료 날짜의 모든 일자에 PENDING run 생성.
              </span>
              <Input
                type="date"
                value={backfillStart}
                onChange={(e) => setBackfillStart(e.target.value)}
                className="h-8 w-36 text-xs"
              />
              <span>→</span>
              <Input
                type="date"
                value={backfillEnd}
                onChange={(e) => setBackfillEnd(e.target.value)}
                className="h-8 w-36 text-xs"
              />
              <Button
                size="sm"
                onClick={handleBackfill}
                disabled={
                  backfill.isPending || !backfillStart || !backfillEnd
                }
              >
                {backfill.isPending && (
                  <Loader2 className="h-3 w-3 animate-spin" />
                )}
                실행
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-1 overflow-hidden rounded-lg border border-border bg-background">
        <NodePaletteV2 onAdd={handlePaletteAdd} />
        <div
          ref={wrapperRef}
          className="flex-1"
          onDragOver={onDragOver}
          onDrop={onDrop}
        >
          <ReactFlow
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
