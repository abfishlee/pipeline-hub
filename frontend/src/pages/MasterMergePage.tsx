import { Play, Undo2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  type MergeCandidateOut,
  type MergeOpOut,
  useMergeCandidates,
  useMergeOps,
  useRunAutoMerge,
  useUnmerge,
} from "@/api/master_merge";
import { ApiError } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

export function MasterMergePage() {
  const [stdCodeFilter, setStdCodeFilter] = useState("");
  const candidates = useMergeCandidates(stdCodeFilter || null);
  const ops = useMergeOps(true);
  const run = useRunAutoMerge();

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
          <span className="text-muted-foreground">std_code:</span>
          <Input
            value={stdCodeFilter}
            onChange={(e) => setStdCodeFilter(e.target.value)}
            placeholder="(전체)"
            className="h-9 max-w-xs"
          />
          <Button
            disabled={run.isPending}
            onClick={() => {
              if (!confirm("자동 머지를 즉시 실행합니다. 분쟁 후보는 PRODUCT_MATCHING crowd 작업으로 전환됩니다.")) return;
              run.mutate(stdCodeFilter || null, {
                onSuccess: (s) =>
                  toast.success(
                    `candidates=${s.candidates} merged=${s.merged} disputed=${s.disputed}`,
                  ),
                onError: (err) =>
                  toast.error(err instanceof ApiError ? err.message : "실패"),
              });
            }}
          >
            <Play className="mr-1 h-3 w-3" />
            {run.isPending ? "실행 중…" : "자동 머지 실행"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-2 p-4">
          <h3 className="text-sm font-semibold">머지 후보 ({candidates.data?.length ?? 0})</h3>
          {candidates.isLoading && (
            <div className="text-sm text-muted-foreground">로딩 중…</div>
          )}
          {candidates.data?.length === 0 && (
            <div className="text-sm text-muted-foreground">후보가 없습니다.</div>
          )}
          {candidates.data?.map((c, idx) => (
            <CandidateCard key={`${c.std_code}-${idx}`} cand={c} />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          <Table>
            <Thead>
              <Tr>
                <Th>op_id</Th>
                <Th>target</Th>
                <Th>sources</Th>
                <Th>mapping</Th>
                <Th>merged_at</Th>
                <Th>state</Th>
                <Th></Th>
              </Tr>
            </Thead>
            <Tbody>
              {ops.data?.length === 0 && (
                <Tr>
                  <Td colSpan={7} className="text-center text-muted-foreground">
                    머지 이력이 없습니다.
                  </Td>
                </Tr>
              )}
              {ops.data?.map((o) => (
                <OpRow key={o.merge_op_id} op={o} />
              ))}
            </Tbody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function CandidateCard({ cand }: { cand: MergeCandidateOut }) {
  return (
    <div className="rounded-md border bg-muted/20 p-3 text-xs">
      <div className="mb-1 flex items-center gap-2">
        <Badge>{cand.std_code}</Badge>
        <span className="text-muted-foreground">cluster_size={cand.cluster_size}</span>
        {cand.cluster_size >= 5 && (
          <Badge variant="destructive">분쟁 (5+ row)</Badge>
        )}
      </div>
      <Table>
        <Thead>
          <Tr>
            <Th>product_id</Th>
            <Th>canonical_name</Th>
            <Th>grade</Th>
            <Th>package</Th>
            <Th>weight_g</Th>
            <Th>confidence</Th>
          </Tr>
        </Thead>
        <Tbody>
          {cand.products.map((p) => (
            <Tr key={p.product_id}>
              <Td className="font-mono">{p.product_id}</Td>
              <Td>{p.canonical_name}</Td>
              <Td>{p.grade ?? "-"}</Td>
              <Td>{p.package_type ?? "-"}</Td>
              <Td className="font-mono">{p.weight_g ?? "-"}</Td>
              <Td className="font-mono">
                {p.confidence_score ? p.confidence_score.toFixed(1) : "-"}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </div>
  );
}

function OpRow({ op }: { op: MergeOpOut }) {
  const unmerge = useUnmerge();
  return (
    <Tr>
      <Td className="font-mono text-xs">{op.merge_op_id}</Td>
      <Td className="font-mono text-xs">{op.target_product_id}</Td>
      <Td className="font-mono text-xs">
        [{op.source_product_ids.join(", ")}]
      </Td>
      <Td className="text-xs">{op.mapping_count ?? "-"}</Td>
      <Td className="text-xs">{formatDateTime(op.merged_at)}</Td>
      <Td>
        {op.is_unmerged ? (
          <Badge variant="muted">unmerged</Badge>
        ) : (
          <Badge variant="success">active</Badge>
        )}
      </Td>
      <Td>
        {!op.is_unmerged && (
          <Button
            size="sm"
            variant="outline"
            disabled={unmerge.isPending}
            onClick={() => {
              if (!confirm("이 머지를 되돌립니까? source product 들이 새 product_id 로 재생성됩니다.")) return;
              unmerge.mutate(op.merge_op_id, {
                onSuccess: (res) =>
                  toast.success(`new_product_ids=[${res.new_product_ids.join(",")}]`),
                onError: (err) =>
                  toast.error(err instanceof ApiError ? err.message : "실패"),
              });
            }}
          >
            <Undo2 className="mr-1 h-3 w-3" />
            Unmerge
          </Button>
        )}
      </Td>
    </Tr>
  );
}
