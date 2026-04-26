// Phase 6 Wave 2B — Transform Designer (workbench 3 코어).
//
// 4 탭 구성:
//   1. SQL Asset      — domain.sql_asset CRUD + transition (SQL_ASSET_TRANSFORM 노드 backing)
//   2. HTTP Provider  — provider_kind=HTTP_TRANSFORM 카탈로그 (read-only)
//   3. Function       — 26+ allowlist 함수 카탈로그 (read-only)
//   4. Provider       — 전체 provider 카탈로그 (read-only)
import { Database, FunctionSquare, Globe, Pencil, Plus, Plug } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { useDomains } from "@/api/v2/domains";
import { type FunctionSpec, useFunctionRegistry } from "@/api/v2/mappings";
import { useProviders } from "@/api/v2/providers";
import {
  type AssetStatus,
  type SqlAsset,
  type SqlAssetIn,
  type SqlAssetUpdate,
  useCreateSqlAsset,
  useDeleteSqlAsset,
  useSqlAssets,
  useTransitionSqlAsset,
  useUpdateSqlAsset,
} from "@/api/v2/sql_assets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/format";

type TabKey = "sql" | "http" | "function" | "provider";

function statusVariant(
  s: AssetStatus,
): "default" | "secondary" | "success" | "warning" | "muted" {
  switch (s) {
    case "DRAFT":
      return "muted";
    case "REVIEW":
      return "warning";
    case "APPROVED":
      return "default";
    case "PUBLISHED":
      return "success";
  }
}

export function TransformDesigner() {
  const [tab, setTab] = useState<TabKey>("sql");

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Transform Designer (workbench 3)</h2>
        <p className="text-sm text-muted-foreground">
          ETL 캔버스에서 사용할 변환 자산 — SQL Asset / HTTP Provider / Function / Provider 카탈로그.
        </p>
      </div>

      {/* Tab strip */}
      <div className="flex flex-wrap gap-1 border-b border-border">
        <TabButton
          active={tab === "sql"}
          onClick={() => setTab("sql")}
          icon={<Database className="h-4 w-4" />}
          label="SQL Asset"
        />
        <TabButton
          active={tab === "http"}
          onClick={() => setTab("http")}
          icon={<Globe className="h-4 w-4" />}
          label="HTTP Provider"
        />
        <TabButton
          active={tab === "function"}
          onClick={() => setTab("function")}
          icon={<FunctionSquare className="h-4 w-4" />}
          label="Function (26+)"
        />
        <TabButton
          active={tab === "provider"}
          onClick={() => setTab("provider")}
          icon={<Plug className="h-4 w-4" />}
          label="Provider"
        />
      </div>

      {tab === "sql" && <SqlAssetTab />}
      {tab === "http" && <HttpProviderTab />}
      {tab === "function" && <FunctionCatalogTab />}
      {tab === "provider" && <ProviderCatalogTab />}
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}

function TabButton({ active, onClick, icon, label }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-2 border-b-2 px-3 py-2 text-sm transition",
        active
          ? "border-primary text-primary"
          : "border-transparent text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Tab 1 — SQL Asset
// ---------------------------------------------------------------------------
function SqlAssetTab() {
  const domains = useDomains();
  const [domainCode, setDomainCode] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<AssetStatus | "">("");

  const assets = useSqlAssets({
    domain_code: domainCode || undefined,
    status: statusFilter || undefined,
  });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<SqlAsset | null>(null);

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="text-xs text-muted-foreground">도메인</label>
              <select
                className="mt-1 h-9 w-48 rounded-md border bg-background px-3 text-sm"
                value={domainCode}
                onChange={(e) => setDomainCode(e.target.value)}
              >
                <option value="">전체</option>
                {domains.data?.map((d) => (
                  <option key={d.domain_code} value={d.domain_code}>
                    {d.domain_code} — {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">상태</label>
              <select
                className="mt-1 h-9 w-36 rounded-md border bg-background px-3 text-sm"
                value={statusFilter}
                onChange={(e) =>
                  setStatusFilter((e.target.value || "") as AssetStatus | "")
                }
              >
                <option value="">전체</option>
                <option value="DRAFT">DRAFT</option>
                <option value="REVIEW">REVIEW</option>
                <option value="APPROVED">APPROVED</option>
                <option value="PUBLISHED">PUBLISHED</option>
              </select>
            </div>
            <div className="ml-auto">
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" />새 SQL Asset
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {assets.isLoading && (
            <div className="p-6 text-sm text-muted-foreground">불러오는 중...</div>
          )}
          {assets.error && (
            <div className="p-6 text-sm text-destructive">
              로드 실패: {(assets.error as Error).message}
            </div>
          )}
          {assets.data && assets.data.length === 0 && (
            <div className="p-6 text-sm text-muted-foreground">
              등록된 SQL Asset 이 없습니다. 우측 상단 "+ 새 SQL Asset" 으로 등록.
            </div>
          )}
          {assets.data && assets.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>asset_code</Th>
                  <Th>도메인</Th>
                  <Th>v</Th>
                  <Th>output_table</Th>
                  <Th>설명</Th>
                  <Th>상태</Th>
                  <Th>업데이트</Th>
                  <Th>동작</Th>
                </Tr>
              </Thead>
              <Tbody>
                {assets.data.map((a) => (
                  <Tr key={a.asset_id}>
                    <Td>
                      <code className="text-xs">{a.asset_code}</code>
                    </Td>
                    <Td className="text-xs">{a.domain_code}</Td>
                    <Td className="text-xs text-muted-foreground">v{a.version}</Td>
                    <Td>
                      {a.output_table ? (
                        <code className="text-xs">{a.output_table}</code>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </Td>
                    <Td className="max-w-xs truncate text-xs">
                      {a.description ?? "—"}
                    </Td>
                    <Td>
                      <Badge variant={statusVariant(a.status)}>{a.status}</Badge>
                    </Td>
                    <Td className="text-xs text-muted-foreground">
                      {formatDateTime(a.updated_at)}
                    </Td>
                    <Td>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(a)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      {creating && (
        <SqlAssetEditDialog
          mode="create"
          open={creating}
          onClose={() => setCreating(false)}
        />
      )}
      {editing && (
        <SqlAssetEditDialog
          mode="edit"
          open={!!editing}
          existing={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}

interface SqlAssetEditDialogProps {
  mode: "create" | "edit";
  open: boolean;
  existing?: SqlAsset;
  onClose: () => void;
}

function SqlAssetEditDialog({
  mode,
  open,
  existing,
  onClose,
}: SqlAssetEditDialogProps) {
  const domains = useDomains();
  const create = useCreateSqlAsset();
  const update = useUpdateSqlAsset(existing?.asset_id ?? 0);
  const transition = useTransitionSqlAsset(existing?.asset_id ?? 0);
  const remove = useDeleteSqlAsset();

  const [form, setForm] = useState<SqlAssetIn>({
    asset_code: "",
    domain_code: "",
    sql_text: "",
    output_table: "",
    description: "",
    version: 1,
  });

  useEffect(() => {
    if (mode === "edit" && existing) {
      setForm({
        asset_code: existing.asset_code,
        domain_code: existing.domain_code,
        sql_text: existing.sql_text,
        output_table: existing.output_table ?? "",
        description: existing.description ?? "",
        version: existing.version,
      });
    } else {
      setForm({
        asset_code: "",
        domain_code: "",
        sql_text: "",
        output_table: "",
        description: "",
        version: 1,
      });
    }
  }, [mode, existing]);

  const isReadOnly = mode === "edit" && existing && existing.status !== "DRAFT";

  async function handleSubmit() {
    try {
      if (mode === "create") {
        await create.mutateAsync({
          ...form,
          output_table: form.output_table?.trim() || null,
          description: form.description?.trim() || null,
        });
        toast.success("SQL Asset 등록 (DRAFT)");
        onClose();
      } else {
        const payload: SqlAssetUpdate = {
          sql_text: form.sql_text,
          output_table: form.output_table?.trim() || null,
          description: form.description?.trim() || null,
        };
        await update.mutateAsync(payload);
        toast.success("저장 완료");
      }
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`저장 실패: ${msg}`);
    }
  }

  async function handleTransition(target: AssetStatus) {
    if (!existing) return;
    try {
      await transition.mutateAsync(target);
      toast.success(`상태 전이: ${existing.status} → ${target}`);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`전이 실패: ${msg}`);
    }
  }

  async function handleDelete() {
    if (!existing) return;
    if (!confirm(`SQL Asset ${existing.asset_code} v${existing.version} 삭제?`))
      return;
    try {
      await remove.mutateAsync(existing.asset_id);
      toast.success("삭제 완료");
      onClose();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      toast.error(`삭제 실패: ${msg}`);
    }
  }

  const transitionsFromCurrent: AssetStatus[] = useMemo(() => {
    if (!existing) return [];
    switch (existing.status) {
      case "DRAFT":
        return ["REVIEW"];
      case "REVIEW":
        return ["APPROVED", "DRAFT"];
      case "APPROVED":
        return ["PUBLISHED", "DRAFT"];
      case "PUBLISHED":
        return ["DRAFT"];
    }
  }, [existing]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? "새 SQL Asset"
              : `SQL Asset 편집 — ${existing?.asset_code} v${existing?.version}`}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">asset_code</label>
              <Input
                value={form.asset_code}
                onChange={(e) =>
                  setForm({ ...form, asset_code: e.target.value })
                }
                disabled={mode === "edit"}
                placeholder="agri_daily_price_clean"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">도메인</label>
              <select
                className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
                value={form.domain_code}
                onChange={(e) =>
                  setForm({ ...form, domain_code: e.target.value })
                }
                disabled={mode === "edit"}
              >
                <option value="">선택</option>
                {domains.data?.map((d) => (
                  <option key={d.domain_code} value={d.domain_code}>
                    {d.domain_code}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">version</label>
              <Input
                type="number"
                min={1}
                value={form.version ?? 1}
                onChange={(e) =>
                  setForm({ ...form, version: parseInt(e.target.value) || 1 })
                }
                disabled={mode === "edit"}
              />
            </div>
          </div>

          <div>
            <label className="text-xs text-muted-foreground">output_table (선택)</label>
            <Input
              value={form.output_table ?? ""}
              onChange={(e) =>
                setForm({ ...form, output_table: e.target.value })
              }
              disabled={!!isReadOnly}
              placeholder="agri_stg.cleaned_2026_04"
            />
          </div>

          <div>
            <label className="text-xs text-muted-foreground">설명 (선택)</label>
            <Input
              value={form.description ?? ""}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              disabled={!!isReadOnly}
              placeholder="일별 가격 정제 SQL"
            />
          </div>

          <div>
            <label className="text-xs text-muted-foreground">SQL 본문</label>
            <textarea
              className="mt-1 h-64 w-full rounded-md border bg-background p-3 font-mono text-xs"
              value={form.sql_text}
              onChange={(e) => setForm({ ...form, sql_text: e.target.value })}
              disabled={!!isReadOnly}
              placeholder="SELECT ... FROM agri_stg.raw_2026 WHERE ..."
            />
            <div className="mt-1 text-xs text-muted-foreground">
              저장 시 sql_guard (SQL_ASSET_TRANSFORM) 검증 — DROP/DELETE/TRUNCATE 등 차단,
              schema 화이트리스트 (wf, stg, {form.domain_code}_stg, {form.domain_code}_mart).
            </div>
          </div>

          {isReadOnly && existing && (
            <div className="rounded-md border border-border bg-muted/40 p-3 text-xs">
              status={existing.status} — DRAFT 만 직접 수정. APPROVED/PUBLISHED 는
              새 version 으로 등록 (Phase 7 backlog: 자동 fork).
            </div>
          )}
        </div>

        <DialogFooter className="flex-wrap gap-2">
          {mode === "edit" && existing && (
            <>
              {transitionsFromCurrent.map((t) => (
                <Button
                  key={t}
                  variant="secondary"
                  size="sm"
                  onClick={() => handleTransition(t)}
                >
                  → {t}
                </Button>
              ))}
              {existing.status !== "PUBLISHED" && (
                <Button variant="destructive" size="sm" onClick={handleDelete}>
                  삭제
                </Button>
              )}
            </>
          )}
          <Button variant="outline" onClick={onClose}>
            닫기
          </Button>
          {!isReadOnly && (
            <Button onClick={handleSubmit}>
              {mode === "create" ? "등록" : "저장"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Tab 2 — HTTP Provider 카탈로그
// ---------------------------------------------------------------------------
function HttpProviderTab() {
  const providers = useProviders("HTTP_TRANSFORM");

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="space-y-1">
          <h3 className="text-sm font-semibold">HTTP_TRANSFORM Provider</h3>
          <p className="text-xs text-muted-foreground">
            HTTP_TRANSFORM 노드가 호출하는 외부 정제 API. provider 등록은 ADMIN 메뉴에서.
            여기서는 ETL 캔버스에서 사용할 수 있는 카탈로그를 확인.
          </p>
        </div>

        {providers.isLoading && (
          <div className="text-sm text-muted-foreground">불러오는 중...</div>
        )}
        {providers.error && (
          <div className="text-sm text-destructive">
            로드 실패 (ADMIN 권한이 필요할 수 있습니다):{" "}
            {(providers.error as Error).message}
          </div>
        )}
        {providers.data && providers.data.length === 0 && (
          <div className="text-sm text-muted-foreground">
            등록된 HTTP_TRANSFORM provider 가 없습니다.
          </div>
        )}
        {providers.data && providers.data.length > 0 && (
          <Table>
            <Thead>
              <Tr>
                <Th>provider_code</Th>
                <Th>kind</Th>
                <Th>impl</Th>
                <Th>설명</Th>
                <Th>활성</Th>
              </Tr>
            </Thead>
            <Tbody>
              {providers.data.map((p) => (
                <Tr key={p.provider_code}>
                  <Td>
                    <code className="text-xs">{p.provider_code}</code>
                  </Td>
                  <Td className="text-xs">{p.provider_kind}</Td>
                  <Td className="text-xs">{p.implementation_type}</Td>
                  <Td className="max-w-md truncate text-xs">
                    {p.description ?? "—"}
                  </Td>
                  <Td>
                    {p.is_active ? (
                      <Badge variant="success">active</Badge>
                    ) : (
                      <Badge variant="muted">disabled</Badge>
                    )}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tab 3 — Function 카탈로그
// ---------------------------------------------------------------------------
function FunctionCatalogTab() {
  const functions = useFunctionRegistry();
  const [filter, setFilter] = useState("");

  const grouped = useMemo(() => {
    const out: Record<string, FunctionSpec[]> = {};
    if (!functions.data) return out;
    const filtered = functions.data.filter((f) => {
      if (!filter) return true;
      const q = filter.toLowerCase();
      return (
        f.name.toLowerCase().includes(q) ||
        f.description.toLowerCase().includes(q) ||
        f.category.toLowerCase().includes(q)
      );
    });
    for (const f of filtered) {
      out[f.category] ??= [];
      out[f.category].push(f);
    }
    return out;
  }, [functions.data, filter]);

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1">
            <h3 className="text-sm font-semibold">Function (mini-DSL allowlist)</h3>
            <p className="text-xs text-muted-foreground">
              transform_expr / SQL_INLINE_TRANSFORM 등에서 사용 가능한 함수.
              Field Mapping Designer 의 transform_expr 에 그대로 입력.
            </p>
          </div>
          <div className="w-64">
            <Input
              placeholder="검색 — name / category / 설명"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
        </div>

        {functions.isLoading && (
          <div className="text-sm text-muted-foreground">불러오는 중...</div>
        )}
        {functions.error && (
          <div className="text-sm text-destructive">
            로드 실패: {(functions.error as Error).message}
          </div>
        )}

        {Object.entries(grouped)
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([category, funcs]) => (
            <div key={category} className="space-y-1">
              <div className="text-xs font-semibold uppercase text-muted-foreground">
                {category} ({funcs.length})
              </div>
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                {funcs.map((f) => (
                  <div
                    key={f.name}
                    className="rounded-md border border-border p-2"
                  >
                    <div className="flex items-center gap-2">
                      <code className="text-xs font-semibold">{f.name}</code>
                      <span className="text-[10px] text-muted-foreground">
                        ({f.arity_min}
                        {f.arity_max === f.arity_min
                          ? ""
                          : f.arity_max === null
                            ? "+"
                            : `~${f.arity_max}`}
                        )
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {f.description}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tab 4 — Provider 카탈로그 (전체)
// ---------------------------------------------------------------------------
function ProviderCatalogTab() {
  const providers = useProviders();
  const [kindFilter, setKindFilter] = useState("");

  const filtered = useMemo(() => {
    if (!providers.data) return [];
    if (!kindFilter) return providers.data;
    return providers.data.filter((p) => p.provider_kind === kindFilter);
  }, [providers.data, kindFilter]);

  const kinds = useMemo(() => {
    if (!providers.data) return [];
    return Array.from(new Set(providers.data.map((p) => p.provider_kind))).sort();
  }, [providers.data]);

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1">
            <h3 className="text-sm font-semibold">전체 Provider 카탈로그</h3>
            <p className="text-xs text-muted-foreground">
              source_provider_binding 으로 source 와 연결되는 모든 provider
              (read-only).
            </p>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">kind</label>
            <select
              className="mt-1 h-9 w-48 rounded-md border bg-background px-3 text-sm"
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value)}
            >
              <option value="">전체</option>
              {kinds.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </div>
        </div>

        {providers.isLoading && (
          <div className="text-sm text-muted-foreground">불러오는 중...</div>
        )}
        {providers.error && (
          <div className="text-sm text-destructive">
            로드 실패 (ADMIN 권한이 필요할 수 있습니다):{" "}
            {(providers.error as Error).message}
          </div>
        )}
        {filtered.length > 0 && (
          <Table>
            <Thead>
              <Tr>
                <Th>provider_code</Th>
                <Th>kind</Th>
                <Th>impl</Th>
                <Th>설명</Th>
                <Th>활성</Th>
              </Tr>
            </Thead>
            <Tbody>
              {filtered.map((p) => (
                <Tr key={p.provider_code}>
                  <Td>
                    <code className="text-xs">{p.provider_code}</code>
                  </Td>
                  <Td className="text-xs">{p.provider_kind}</Td>
                  <Td className="text-xs">{p.implementation_type}</Td>
                  <Td className="max-w-md truncate text-xs">
                    {p.description ?? "—"}
                  </Td>
                  <Td>
                    {p.is_active ? (
                      <Badge variant="success">active</Badge>
                    ) : (
                      <Badge variant="muted">disabled</Badge>
                    )}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
