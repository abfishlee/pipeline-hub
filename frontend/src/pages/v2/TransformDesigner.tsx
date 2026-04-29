import {
  Ban,
  CheckCircle2,
  Code2,
  Database,
  Loader2,
  Search,
  Sparkles,
} from "lucide-react";
import type React from "react";
import { useState } from "react";
import { toast } from "sonner";
import { useDomains } from "@/api/v2/domains";
import {
  type AssetStatus,
  type ModelCategory,
  type SqlAsset,
  type SqlAssetType,
  useSqlAssets,
  useToggleSqlAssetActive,
} from "@/api/v2/sql_assets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime } from "@/lib/format";

const CATEGORIES: { value: ModelCategory; label: string }[] = [
  { value: "TRANSFORM", label: "Transform" },
  { value: "DQ", label: "DQ" },
  { value: "STANDARDIZATION", label: "Standardization" },
  { value: "ENRICHMENT", label: "Enrichment" },
  { value: "LOAD", label: "Load" },
  { value: "OTHER", label: "Other" },
];

const TYPES: { value: SqlAssetType; label: string; language: "SQL" | "Python" }[] = [
  { value: "TRANSFORM_SQL", label: "Transform SQL", language: "SQL" },
  { value: "STANDARDIZATION_SQL", label: "Standardization SQL", language: "SQL" },
  { value: "QUALITY_CHECK_SQL", label: "DQ SQL", language: "SQL" },
  { value: "DML_SCRIPT", label: "DML SQL", language: "SQL" },
  { value: "FUNCTION", label: "SQL Function", language: "SQL" },
  { value: "PROCEDURE", label: "SQL Procedure", language: "SQL" },
  { value: "PYTHON_SCRIPT", label: "Python Model", language: "Python" },
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

function languageOf(assetType: string): "SQL" | "Python" {
  return assetType === "PYTHON_SCRIPT" ? "Python" : "SQL";
}

export function TransformDesigner() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState("agri_price");
  const [category, setCategory] = useState<ModelCategory | "">("");
  const [type, setType] = useState<SqlAssetType | "">("");
  const [status, setStatus] = useState<AssetStatus | "">("");
  const [activeOnly, setActiveOnly] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [selected, setSelected] = useState<SqlAsset | null>(null);

  const assets = useSqlAssets({
    domain_code: domainCode || undefined,
    model_category: category || undefined,
    asset_type: type || undefined,
    status: status || undefined,
    is_active: activeOnly ? true : undefined,
  });

  const visible = (assets.data ?? []).filter((asset) => {
    const q = keyword.trim().toLowerCase();
    if (!q) return true;
    return (
      asset.asset_code.toLowerCase().includes(q) ||
      (asset.description ?? "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">모형 레포지토리</h2>
          <p className="max-w-4xl text-sm text-muted-foreground">
            Canvas에서 저장한 SQL/Python 처리 모형을 조회하고 운영 상태를 관리합니다.
            모형의 신규 작성과 설계는 Canvas의 SQL Model 또는 Python Model 노드에서 합니다.
          </p>
        </div>
        <div className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
          <div className="font-semibold text-foreground">권장 흐름</div>
          Source - Field Mapping - SQL/Python Model - Mart Load
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[1fr_360px]">
        <Card>
          <CardContent className="space-y-3 p-4">
            <div className="grid gap-3 md:grid-cols-5">
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
                카테고리
                <select
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground"
                  value={category}
                  onChange={(e) => setCategory((e.target.value || "") as ModelCategory | "")}
                >
                  <option value="">전체</option>
                  {CATEGORIES.map((c) => (
                    <option key={c.value} value={c.value}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs font-medium text-muted-foreground">
                실행 방식
                <select
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm text-foreground"
                  value={type}
                  onChange={(e) => setType((e.target.value || "") as SqlAssetType | "")}
                >
                  <option value="">전체</option>
                  {TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-xs font-medium text-muted-foreground">
                상태
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
              <label className="flex items-end gap-2 pb-2 text-xs font-medium text-muted-foreground">
                <input
                  type="checkbox"
                  checked={activeOnly}
                  onChange={(e) => setActiveOnly(e.target.checked)}
                />
                활성 모형만
              </label>
            </div>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-9"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="모형 코드나 설명으로 검색"
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-2 p-4 text-sm">
            <div className="flex items-center gap-2 font-semibold">
              <Sparkles className="h-4 w-4 text-primary" />
              Canvas에서 만드는 모형
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              SQL Model은 DB 안에서 대량 변환, 집계, 적재 전처리에 적합합니다. Python Model은
              OCR 결과 파싱, 복잡한 문자열 처리, 외부 보강처럼 SQL보다 코드가 자연스러운 작업에
              씁니다.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="p-0">
          {assets.isLoading && (
            <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              모형을 불러오는 중입니다.
            </div>
          )}
          {assets.error && (
            <div className="p-6 text-sm text-destructive">
              조회 실패: {(assets.error as Error).message}
            </div>
          )}
          {!assets.isLoading && visible.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              조건에 맞는 모형이 없습니다. Canvas에서 SQL Model 또는 Python Model을 작성한 뒤
              모형으로 저장해보세요.
            </div>
          )}
          {visible.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>모형</Th>
                  <Th>카테고리</Th>
                  <Th>실행 방식</Th>
                  <Th>출력</Th>
                  <Th>상태</Th>
                  <Th>운영</Th>
                  <Th>수정일</Th>
                </Tr>
              </Thead>
              <Tbody>
                {visible.map((asset) => (
                  <Tr
                    key={asset.asset_id}
                    className="cursor-pointer"
                    onClick={() => setSelected(asset)}
                  >
                    <Td>
                      <div className="font-mono text-sm font-semibold">{asset.asset_code}</div>
                      <div className="max-w-[360px] truncate text-xs text-muted-foreground">
                        {asset.description || `${asset.domain_code} v${asset.version}`}
                      </div>
                    </Td>
                    <Td>
                      <Badge variant="secondary">{asset.model_category}</Badge>
                    </Td>
                    <Td>
                      <Badge variant={languageOf(asset.asset_type) === "Python" ? "warning" : "default"}>
                        {languageOf(asset.asset_type)}
                      </Badge>
                    </Td>
                    <Td className="max-w-[240px] truncate font-mono text-xs">
                      {asset.output_table || "Canvas output"}
                    </Td>
                    <Td>
                      <Badge variant={STATUS_VARIANT[asset.status]}>{asset.status}</Badge>
                    </Td>
                    <Td>
                      <ActiveButton asset={asset} />
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {formatDateTime(asset.updated_at)}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {selected && <ModelDetail asset={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function ActiveButton({ asset }: { asset: SqlAsset }) {
  const toggle = useToggleSqlAssetActive(asset.asset_id);
  const handleClick = async (event: React.MouseEvent) => {
    event.stopPropagation();
    try {
      await toggle.mutateAsync(!asset.is_active);
      toast.success(asset.is_active ? "모형을 비활성화했습니다." : "모형을 활성화했습니다.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "상태 변경 실패");
    }
  };
  return (
    <Button
      size="sm"
      variant={asset.is_active ? "outline" : "secondary"}
      onClick={handleClick}
      disabled={toggle.isPending}
    >
      {asset.is_active ? <CheckCircle2 className="h-3 w-3" /> : <Ban className="h-3 w-3" />}
      {asset.is_active ? "활성" : "비활성"}
    </Button>
  );
}

function ModelDetail({ asset, onClose }: { asset: SqlAsset; onClose: () => void }) {
  const type = TYPES.find((t) => t.value === asset.asset_type);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>모형 상세</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <Card>
            <CardContent className="space-y-3 p-4 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">model_code</div>
                <div className="font-mono font-semibold">{asset.asset_code}</div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <Info label="domain" value={asset.domain_code} />
                <Info label="version" value={`v${asset.version}`} />
                <Info label="category" value={asset.model_category} />
                <Info label="language" value={type?.language ?? languageOf(asset.asset_type)} />
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant={STATUS_VARIANT[asset.status]}>{asset.status}</Badge>
                <Badge variant={asset.is_active ? "success" : "muted"}>
                  {asset.is_active ? "ACTIVE" : "INACTIVE"}
                </Badge>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">output_table</div>
                <div className="break-all font-mono text-xs">
                  {asset.output_table || "Canvas 실행 시 결정"}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">description</div>
                <div className="text-xs leading-5">{asset.description || "-"}</div>
              </div>
              <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
                <div className="mb-1 flex items-center gap-1 font-semibold text-foreground">
                  <Database className="h-3 w-3" />
                  사용 위치
                </div>
                Canvas에서 SQL Model 또는 Python Model 노드의 asset_code로 이 모형을 선택해
                실행합니다.
              </div>
            </CardContent>
          </Card>
          <div className="space-y-2">
            <div className="flex items-center gap-1 text-xs font-semibold text-muted-foreground">
              <Code2 className="h-3 w-3" />
              {type?.language ?? languageOf(asset.asset_type)} body
            </div>
            <pre className="max-h-[640px] overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs leading-5">
              {asset.sql_text}
            </pre>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-mono text-xs">{value}</div>
    </div>
  );
}
