import { useState } from "react";
import { Link } from "react-router-dom";
import {
  type PipelineReleaseOut,
  usePipelineReleaseDetail,
  usePipelineReleases,
  useWorkflows,
} from "@/api/pipelines";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

export function PipelineReleases() {
  const workflows = useWorkflows({ limit: 100 });
  const [filterName, setFilterName] = useState<string>("");
  const releases = usePipelineReleases(filterName || null);
  const [selectedReleaseId, setSelectedReleaseId] = useState<number | null>(null);
  const detail = usePipelineReleaseDetail(selectedReleaseId);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
          <span className="text-muted-foreground">workflow_name 필터:</span>
          <select
            value={filterName}
            onChange={(e) => setFilterName(e.target.value)}
            className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">(전체)</option>
            {Array.from(
              new Set((workflows.data ?? []).map((w) => w.name)),
            ).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <p className="basis-full text-xs text-muted-foreground">
            ※ 배포 이력은 PUBLISHED 시점의 그래프 스냅샷을 동봉합니다 — 원본 DRAFT 가
            이후 변경돼도 release 는 동결.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <Thead>
              <Tr>
                <Th>release_id</Th>
                <Th>workflow_name</Th>
                <Th>version</Th>
                <Th>변경 요약</Th>
                <Th>released_at</Th>
                <Th></Th>
              </Tr>
            </Thead>
            <Tbody>
              {releases.isLoading && (
                <Tr>
                  <Td colSpan={6} className="text-center text-muted-foreground">
                    로딩 중…
                  </Td>
                </Tr>
              )}
              {!releases.isLoading && (releases.data?.length ?? 0) === 0 && (
                <Tr>
                  <Td colSpan={6} className="text-center text-muted-foreground">
                    배포 이력이 없습니다.
                  </Td>
                </Tr>
              )}
              {releases.data?.map((r) => (
                <Tr key={r.release_id}>
                  <Td className="font-mono">#{r.release_id}</Td>
                  <Td>{r.workflow_name}</Td>
                  <Td className="font-mono">v{r.version_no}</Td>
                  <Td>
                    <ChangeSummaryInline release={r} />
                  </Td>
                  <Td>{formatDateTime(r.released_at)}</Td>
                  <Td className="space-x-2 whitespace-nowrap">
                    <button
                      type="button"
                      className="text-primary underline"
                      onClick={() => setSelectedReleaseId(r.release_id)}
                    >
                      상세
                    </button>
                    <Link
                      to={`/v2/pipelines/designer/${r.released_workflow_id}`}
                      className="text-primary underline"
                    >
                      워크플로
                    </Link>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardContent>
      </Card>

      {selectedReleaseId && detail.data && (
        <Card>
          <CardContent className="space-y-2 p-4 text-xs">
            <div className="mb-2 flex items-center gap-2">
              <h3 className="text-sm font-semibold">
                Release #{detail.data.release_id} 상세
              </h3>
              <Badge variant="default">v{detail.data.version_no}</Badge>
              <button
                type="button"
                onClick={() => setSelectedReleaseId(null)}
                className="ml-auto text-xs text-muted-foreground underline"
              >
                닫기
              </button>
            </div>
            <ChangeSummaryDetail release={detail.data} />
            <details>
              <summary className="cursor-pointer">
                노드 스냅샷 ({detail.data.nodes_snapshot.length})
              </summary>
              <pre className="mt-1 max-h-64 overflow-auto rounded bg-muted/40 p-2 font-mono text-[10px]">
                {JSON.stringify(detail.data.nodes_snapshot, null, 2)}
              </pre>
            </details>
            <details>
              <summary className="cursor-pointer">
                엣지 스냅샷 ({detail.data.edges_snapshot.length})
              </summary>
              <pre className="mt-1 max-h-64 overflow-auto rounded bg-muted/40 p-2 font-mono text-[10px]">
                {JSON.stringify(detail.data.edges_snapshot, null, 2)}
              </pre>
            </details>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function ChangeSummaryInline({ release }: { release: PipelineReleaseOut }) {
  const s = release.change_summary;
  const parts: string[] = [];
  if (s.added?.length) parts.push(`+${s.added.length}`);
  if (s.removed?.length) parts.push(`-${s.removed.length}`);
  if (s.changed?.length) parts.push(`~${s.changed.length}`);
  if (!parts.length) return <span className="text-muted-foreground">변경 없음</span>;
  return <span className="font-mono text-xs">{parts.join(" ")}</span>;
}

function ChangeSummaryDetail({ release }: { release: PipelineReleaseOut }) {
  const s = release.change_summary;
  return (
    <div className="grid grid-cols-2 gap-2">
      <SummaryBlock title="추가" tone="emerald" items={s.added ?? []} />
      <SummaryBlock title="제거" tone="rose" items={s.removed ?? []} />
      <SummaryBlock title="변경" tone="amber" items={s.changed ?? []} />
      <SummaryBlock
        title="엣지 +/-"
        tone="zinc"
        items={[...(s.edges_added ?? []).map((e) => `+ ${e}`), ...(s.edges_removed ?? []).map((e) => `- ${e}`)]}
      />
    </div>
  );
}

function SummaryBlock({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "emerald" | "rose" | "amber" | "zinc";
  items: string[];
}) {
  const palette: Record<string, string> = {
    emerald: "border-emerald-300 bg-emerald-50 text-emerald-700",
    rose: "border-rose-300 bg-rose-50 text-rose-700",
    amber: "border-amber-300 bg-amber-50 text-amber-700",
    zinc: "border-zinc-200 bg-muted/40 text-muted-foreground",
  };
  return (
    <div className={`rounded-md border p-2 ${palette[tone]}`}>
      <div className="mb-1 font-semibold">{title} ({items.length})</div>
      {items.length === 0 ? (
        <div className="text-[10px] opacity-70">없음</div>
      ) : (
        <ul className="space-y-0.5 font-mono text-[11px]">
          {items.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
