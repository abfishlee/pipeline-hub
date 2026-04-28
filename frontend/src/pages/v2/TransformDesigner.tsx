import {
  CheckCircle2,
  Code2,
  Loader2,
  Plus,
  Save,
  ShieldCheck,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useDomains } from "@/api/v2/domains";
import {
  type AssetStatus,
  type SqlAsset,
  type SqlAssetType,
  useCreateSqlAsset,
  useDeleteSqlAsset,
  useSqlAssets,
  useTransitionSqlAsset,
  useUpdateSqlAsset,
} from "@/api/v2/sql_assets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

const ASSET_TYPES: { value: SqlAssetType; label: string; help: string }[] = [
  {
    value: "TRANSFORM_SQL",
    label: "Transform SQL",
    help: "평탄화된 staging 데이터를 계산/타입 변환/필터링합니다.",
  },
  {
    value: "STANDARDIZATION_SQL",
    label: "Standardization SQL",
    help: "표준코드, 표준단위, 표준명으로 맞춥니다.",
  },
  {
    value: "QUALITY_CHECK_SQL",
    label: "Quality Check SQL",
    help: "품질검사용 SELECT입니다. 실패 행 또는 검증 결과를 반환합니다.",
  },
  {
    value: "DML_SCRIPT",
    label: "DML Script",
    help: "승인 후 INSERT/UPDATE/DELETE를 실행합니다.",
  },
  {
    value: "FUNCTION",
    label: "SQL Function",
    help: "CREATE OR REPLACE FUNCTION으로 재사용 함수를 등록합니다.",
  },
  {
    value: "PROCEDURE",
    label: "Procedure",
    help: "CREATE OR REPLACE PROCEDURE로 절차형 SQL을 등록합니다.",
  },
];

const STATUS_VARIANT: Record<
  AssetStatus,
  "default" | "secondary" | "success" | "warning" | "muted"
> = {
  DRAFT: "muted",
  REVIEW: "warning",
  APPROVED: "default",
  PUBLISHED: "success",
};

const TYPE_BADGE: Record<SqlAssetType, "default" | "secondary" | "muted" | "warning"> = {
  TRANSFORM_SQL: "default",
  STANDARDIZATION_SQL: "secondary",
  QUALITY_CHECK_SQL: "warning",
  DML_SCRIPT: "muted",
  FUNCTION: "secondary",
  PROCEDURE: "secondary",
};

function starterSql(assetType: SqlAssetType) {
  switch (assetType) {
    case "QUALITY_CHECK_SQL":
      return [
        "SELECT *",
        "FROM {{input_table}}",
        "WHERE product_name IS NULL",
      ].join("\n");
    case "STANDARDIZATION_SQL":
      return [
        "SELECT",
        "  *,",
        "  product_name AS std_product_name",
        "FROM {{input_table}}",
      ].join("\n");
    case "DML_SCRIPT":
      return [
        "INSERT INTO agri_price_stg.example_target (product_name)",
        "SELECT product_name",
        "FROM {{input_table}}",
      ].join("\n");
    case "FUNCTION":
      return [
        "CREATE OR REPLACE FUNCTION dq_is_not_null(value text)",
        "RETURNS integer AS $$",
        "BEGIN",
        "  IF value IS NULL OR length(trim(value)) = 0 THEN",
        "    RETURN 0;",
        "  END IF;",
        "  RETURN 1;",
        "END;",
        "$$ LANGUAGE plpgsql;",
      ].join("\n");
    case "PROCEDURE":
      return [
        "CREATE OR REPLACE PROCEDURE agri_price_stg.example_refresh()",
        "LANGUAGE plpgsql AS $$",
        "BEGIN",
        "  -- approved procedure body",
        "END;",
        "$$;",
      ].join("\n");
    default:
      return [
        "SELECT",
        "  *,",
        "  NULLIF(regexp_replace(sale_price::text, '[^0-9.-]', '', 'g'), '')::numeric AS sale_price_num",
        "FROM {{input_table}}",
      ].join("\n");
  }
}

export function TransformDesigner() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("agri_price");
  const [assetType, setAssetType] = useState<SqlAssetType | "">("");
  const [status, setStatus] = useState<AssetStatus | "">("");
  const assets = useSqlAssets({
    domain_code: domainCode || undefined,
    asset_type: assetType || undefined,
    status: status || undefined,
  });
  const [editing, setEditing] = useState<SqlAsset | null>(null);
  const [creating, setCreating] = useState(false);

  const visibleAssets = assets.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">SQL Studio</h2>
          <p className="max-w-4xl text-sm text-muted-foreground">
            Canvas에서 사용할 SQL 자산을 한 곳에서 관리합니다. Transform, Standardization,
            Quality Check, DML, Function, Procedure를 자산 타입으로 구분하고 Job 실행 이력은
            Canvas 노드 단위로 추적합니다.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" />
          새 SQL 자산
        </Button>
      </div>

      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="grid gap-3 lg:grid-cols-[180px_220px_150px_1fr]">
            <label className="space-y-1 text-xs font-medium text-muted-foreground">
              도메인
              <select
                className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground"
                value={domainCode}
                onChange={(e) => setDomainCode(e.target.value)}
              >
                <option value="">전체</option>
                {domains.data?.map((d) => (
                  <option key={d.domain_code} value={d.domain_code}>
                    {d.domain_code}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs font-medium text-muted-foreground">
              Asset Type
              <select
                className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground"
                value={assetType}
                onChange={(e) => setAssetType((e.target.value || "") as SqlAssetType | "")}
              >
                <option value="">전체</option>
                {ASSET_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs font-medium text-muted-foreground">
              Status
              <select
                className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground"
                value={status}
                onChange={(e) => setStatus((e.target.value || "") as AssetStatus | "")}
              >
                <option value="">전체</option>
                <option value="DRAFT">DRAFT</option>
                <option value="REVIEW">REVIEW</option>
                <option value="APPROVED">APPROVED</option>
                <option value="PUBLISHED">PUBLISHED</option>
              </select>
            </label>
            <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
              <div className="mb-1 font-semibold text-foreground">Canvas parameter</div>
              SQL 안에서 <code>{"{{input_table}}"}</code>, <code>{"{{output_table}}"}</code>,{" "}
              <code>{"{{run_id}}"}</code>, <code>{"{{domain_code}}"}</code>를 사용할 수 있습니다.
              선행 노드가 있으면 <code>{"{{input_table}}"}</code>은 선행 output table로 자동 치환됩니다.
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {assets.isLoading && (
            <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              SQL 자산을 불러오는 중입니다.
            </div>
          )}
          {assets.error && (
            <div className="p-6 text-sm text-destructive">
              조회 실패: {(assets.error as Error).message}
            </div>
          )}
          {!assets.isLoading && visibleAssets.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              등록된 SQL 자산이 없습니다. 오른쪽 위의 새 SQL 자산으로 시작하세요.
            </div>
          )}
          {visibleAssets.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>Asset</Th>
                  <Th>Type</Th>
                  <Th>Output</Th>
                  <Th>Status</Th>
                  <Th>Updated</Th>
                  <Th>Action</Th>
                </Tr>
              </Thead>
              <Tbody>
                {visibleAssets.map((asset) => (
                  <Tr key={asset.asset_id}>
                    <Td>
                      <div className="font-mono text-sm font-semibold">
                        {asset.asset_code}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {asset.domain_code} · v{asset.version}
                      </div>
                    </Td>
                    <Td>
                      <Badge variant={TYPE_BADGE[asset.asset_type]}>
                        {ASSET_TYPES.find((t) => t.value === asset.asset_type)?.label ??
                          asset.asset_type}
                      </Badge>
                    </Td>
                    <Td className="max-w-[260px] truncate font-mono text-xs">
                      {asset.output_table || "Canvas default / script"}
                    </Td>
                    <Td>
                      <Badge variant={STATUS_VARIANT[asset.status]}>
                        {asset.status}
                      </Badge>
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {formatDateTime(asset.updated_at)}
                    </Td>
                    <Td>
                      <Button size="sm" variant="outline" onClick={() => setEditing(asset)}>
                        편집
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {(creating || editing) && (
        <SqlAssetDialog
          asset={editing}
          defaultDomain={domainCode || "agri_price"}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

function SqlAssetDialog({
  asset,
  defaultDomain,
  onClose,
}: {
  asset: SqlAsset | null;
  defaultDomain: string;
  onClose: () => void;
}) {
  const isEdit = !!asset;
  const [assetCode, setAssetCode] = useState(asset?.asset_code ?? "");
  const [domainCode, setDomainCode] = useState(asset?.domain_code ?? defaultDomain);
  const [version, setVersion] = useState(asset?.version ?? 1);
  const [assetType, setAssetType] = useState<SqlAssetType>(
    asset?.asset_type ?? "TRANSFORM_SQL",
  );
  const [outputTable, setOutputTable] = useState(asset?.output_table ?? "");
  const [description, setDescription] = useState(asset?.description ?? "");
  const [sqlText, setSqlText] = useState(asset?.sql_text ?? starterSql("TRANSFORM_SQL"));
  const create = useCreateSqlAsset();
  const update = useUpdateSqlAsset(asset?.asset_id ?? 0);
  const remove = useDeleteSqlAsset();
  const transition = useTransitionSqlAsset(asset?.asset_id ?? 0);

  const selectedType = useMemo(
    () => ASSET_TYPES.find((t) => t.value === assetType),
    [assetType],
  );
  const editable = !asset || asset.status === "DRAFT";

  const handleTypeChange = (next: SqlAssetType) => {
    setAssetType(next);
    if (!asset && !sqlText.trim()) setSqlText(starterSql(next));
    if (!asset) setSqlText(starterSql(next));
  };

  const save = async () => {
    if (!assetCode.trim()) {
      toast.error("asset_code를 입력해 주세요.");
      return;
    }
    if (!sqlText.trim()) {
      toast.error("SQL을 입력해 주세요.");
      return;
    }
    try {
      if (asset) {
        await update.mutateAsync({
          asset_type: assetType,
          sql_text: sqlText,
          output_table: outputTable || null,
          description: description || null,
        });
        toast.success("SQL 자산을 저장했습니다.");
      } else {
        await create.mutateAsync({
          asset_code: assetCode,
          domain_code: domainCode,
          version,
          asset_type: assetType,
          sql_text: sqlText,
          output_table: outputTable || null,
          description: description || null,
        });
        toast.success("SQL 자산을 만들었습니다.");
      }
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "저장 실패");
    }
  };

  const moveStatus = async (status: AssetStatus) => {
    if (!asset) return;
    try {
      await transition.mutateAsync(status);
      toast.success(`${status} 상태로 변경했습니다.`);
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "상태 변경 실패");
    }
  };

  const deleteAsset = async () => {
    if (!asset) return;
    if (!window.confirm(`${asset.asset_code} v${asset.version}을 삭제할까요?`)) return;
    try {
      await remove.mutateAsync(asset.asset_id);
      toast.success("삭제했습니다.");
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "삭제 실패");
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-6xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{asset ? "SQL 자산 편집" : "새 SQL 자산"}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
          <div className="space-y-3">
            <Card>
              <CardContent className="space-y-3 p-4">
                <label className="space-y-1 text-xs font-medium text-muted-foreground">
                  asset_code
                  <Input
                    value={assetCode}
                    onChange={(e) => setAssetCode(e.target.value)}
                    disabled={isEdit}
                    placeholder="clean_hanarum_price"
                  />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <label className="space-y-1 text-xs font-medium text-muted-foreground">
                    domain
                    <Input
                      value={domainCode}
                      onChange={(e) => setDomainCode(e.target.value)}
                      disabled={isEdit}
                    />
                  </label>
                  <label className="space-y-1 text-xs font-medium text-muted-foreground">
                    version
                    <Input
                      type="number"
                      value={version}
                      onChange={(e) => setVersion(Number(e.target.value) || 1)}
                      disabled={isEdit}
                      min={1}
                    />
                  </label>
                </div>
                <label className="space-y-1 text-xs font-medium text-muted-foreground">
                  asset_type
                  <select
                    className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground"
                    value={assetType}
                    onChange={(e) => handleTypeChange(e.target.value as SqlAssetType)}
                    disabled={!editable}
                  >
                    {ASSET_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
                  {selectedType?.help}
                </p>
                <label className="space-y-1 text-xs font-medium text-muted-foreground">
                  output_table
                  <Input
                    value={outputTable}
                    onChange={(e) => setOutputTable(e.target.value)}
                    disabled={!editable}
                    placeholder="비우면 Canvas 실행 시 wf.tmp_run_* 자동 생성"
                  />
                </label>
                <label className="space-y-1 text-xs font-medium text-muted-foreground">
                  description
                  <Input
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    disabled={!editable}
                    placeholder="이 SQL 자산의 의도"
                  />
                </label>
              </CardContent>
            </Card>

            {asset && (
              <Card>
                <CardContent className="space-y-2 p-4 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">상태</span>
                    <Badge variant={STATUS_VARIANT[asset.status]}>{asset.status}</Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {asset.status === "DRAFT" && (
                      <Button size="sm" variant="outline" onClick={() => moveStatus("REVIEW")}>
                        <ShieldCheck className="h-3 w-3" />
                        REVIEW
                      </Button>
                    )}
                    {asset.status === "REVIEW" && (
                      <>
                        <Button size="sm" variant="outline" onClick={() => moveStatus("DRAFT")}>
                          DRAFT
                        </Button>
                        <Button size="sm" onClick={() => moveStatus("APPROVED")}>
                          <CheckCircle2 className="h-3 w-3" />
                          APPROVE
                        </Button>
                      </>
                    )}
                    {asset.status === "APPROVED" && (
                      <Button size="sm" onClick={() => moveStatus("PUBLISHED")}>
                        <Sparkles className="h-3 w-3" />
                        PUBLISH
                      </Button>
                    )}
                    {asset.status === "PUBLISHED" && (
                      <Button size="sm" variant="outline" onClick={() => moveStatus("DRAFT")}>
                        DRAFT로 되돌리기
                      </Button>
                    )}
                    {asset.status !== "PUBLISHED" && (
                      <Button size="sm" variant="destructive" onClick={deleteAsset}>
                        <Trash2 className="h-3 w-3" />
                        삭제
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>

          <div className="space-y-3">
            <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
              <div className="mb-1 flex items-center gap-1 font-semibold text-foreground">
                <Code2 className="h-3 w-3" />
                Canvas에서 사용할 수 있는 파라미터
              </div>
              <code>{"{{input_table}}"}</code>은 선행 노드의 output table,{" "}
              <code>{"{{output_table}}"}</code>은 이 노드의 결과 테이블,{" "}
              <code>{"{{run_id}}"}</code>는 실행 ID, <code>{"{{domain_code}}"}</code>는 도메인으로 치환됩니다.
            </div>
            <textarea
              value={sqlText}
              onChange={(e) => setSqlText(e.target.value)}
              disabled={!editable}
              spellCheck={false}
              className="min-h-[520px] w-full resize-y rounded-md border bg-background p-3 font-mono text-xs leading-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            닫기
          </Button>
          <Button onClick={save} disabled={!editable || create.isPending || update.isPending}>
            {create.isPending || update.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Save className="h-4 w-4" />
            )}
            저장
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
