// Phase 6 Wave 4 — v2 Node config drawer with asset dropdowns.
//
// 박스 종류별로 *어떤 자산을 사용할지* dropdown 을 노출.
// 자산이 없으면 "+ 새 자산 만들기" 버튼 → 해당 designer 로 이동.
import { ExternalLink, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { NodeType } from "@/api/pipelines";
import { useConnectors } from "@/api/v2/connectors";
import { useInboundChannels } from "@/api/v2/inbound_channels";
import { useLoadPolicies } from "@/api/v2/load_policies";
import { useContractsLight } from "@/api/v2/mappings";
import { useProviders } from "@/api/v2/providers";
import { useSqlAssets } from "@/api/v2/sql_assets";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export interface DesignerNodeDataV2 {
  node_key: string;
  node_type: NodeType;
  config_json: Record<string, unknown>;
  position_x: number;
  position_y: number;
  [key: string]: unknown;
}

interface Props {
  selected: DesignerNodeDataV2 | null;
  onChange: (next: DesignerNodeDataV2) => void;
  onDelete?: () => void;
}

export function NodeConfigPanelV2({ selected, onChange, onDelete }: Props) {
  const [keyDraft, setKeyDraft] = useState("");
  const [jsonDraft, setJsonDraft] = useState("{}");
  const [jsonError, setJsonError] = useState<string | null>(null);

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

  if (!selected) {
    return (
      <aside className="flex w-96 shrink-0 flex-col border-l border-border bg-background p-3 text-xs text-muted-foreground">
        <div className="mb-2 text-xs font-semibold uppercase">노드 설정</div>
        <p>좌측 캔버스에서 노드를 선택하면 자산을 연결할 수 있습니다.</p>
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

  function patchConfig(patch: Record<string, unknown>) {
    const merged = { ...selected!.config_json, ...patch };
    setJsonDraft(JSON.stringify(merged, null, 2));
    onChange({ ...selected!, config_json: merged });
  }

  return (
    <aside className="flex w-96 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border bg-background p-3">
      <div className="text-xs font-semibold uppercase text-muted-foreground">
        노드 설정 — {selected.node_type}
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
              placeholder="예: fetch_kamis"
              className="h-9 text-xs font-mono"
            />
          </div>
        </CardContent>
      </Card>

      {/* 박스 종류별 자산 dropdown */}
      <AssetSection
        node_type={selected.node_type}
        config={selected.config_json}
        onPatch={patchConfig}
      />

      {/* JSON editor — 고급 설정 (기본 닫힘) */}
      <details className="rounded-md border border-border bg-background text-xs">
        <summary className="cursor-pointer px-3 py-2 font-semibold text-muted-foreground hover:bg-secondary">
          🔧 고급 설정 (raw JSON)
        </summary>
        <div className="space-y-2 px-3 pb-3 pt-2">
          <div className="flex items-center justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={commitJson}
              className="h-6 text-[10px]"
            >
              <Save className="h-3 w-3" />적용
            </Button>
          </div>
          <textarea
            value={jsonDraft}
            onChange={(e) => setJsonDraft(e.target.value)}
            spellCheck={false}
            className="h-44 w-full resize-none rounded-md border border-input bg-background p-2 font-mono text-[11px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {jsonError && (
            <p className="text-[11px] text-rose-600">파싱 오류: {jsonError}</p>
          )}
          <p className="text-[10px] text-muted-foreground">
            ※ 자산 dropdown 변경은 자동 반영. raw JSON 편집 후 "적용" 클릭.
          </p>
        </div>
      </details>

      {onDelete && (
        <Button variant="destructive" size="sm" onClick={onDelete}>
          노드 삭제
        </Button>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// 자산 dropdown
// ---------------------------------------------------------------------------
interface AssetSectionProps {
  node_type: NodeType;
  config: Record<string, unknown>;
  onPatch: (patch: Record<string, unknown>) => void;
}

function AssetSection({ node_type, config, onPatch }: AssetSectionProps) {
  switch (node_type) {
    case "PUBLIC_API_FETCH":
      return <PublicApiFetchAsset config={config} onPatch={onPatch} />;
    case "MAP_FIELDS":
      return <MapFieldsAsset config={config} onPatch={onPatch} />;
    case "SQL_ASSET_TRANSFORM":
      return <SqlAssetAsset config={config} onPatch={onPatch} />;
    case "LOAD_TARGET":
      return <LoadTargetAsset config={config} onPatch={onPatch} />;
    case "HTTP_TRANSFORM":
      return <HttpTransformAsset config={config} onPatch={onPatch} />;
    // Phase 7 Wave 1A — inbound channel based 3 sources
    case "WEBHOOK_INGEST":
      return (
        <InboundChannelAsset
          config={config}
          onPatch={onPatch}
          channelKindFilter="WEBHOOK"
        />
      );
    case "FILE_UPLOAD_INGEST":
      return (
        <InboundChannelAsset
          config={config}
          onPatch={onPatch}
          channelKindFilter="FILE_UPLOAD"
        />
      );
    case "DB_INCREMENTAL_FETCH":
      return <DbIncrementalAsset config={config} onPatch={onPatch} />;
    // Phase 8.4 — 외부 OCR/Crawler push 결과 + CDC stub
    case "OCR_RESULT_INGEST":
      return (
        <InboundChannelAsset
          config={config}
          onPatch={onPatch}
          channelKindFilter="OCR_RESULT"
        />
      );
    case "CRAWLER_RESULT_INGEST":
      return (
        <InboundChannelAsset
          config={config}
          onPatch={onPatch}
          channelKindFilter="CRAWLER_RESULT"
        />
      );
    case "CDC_EVENT_FETCH":
      return <CdcStubAsset />;
    default:
      return (
        <Card>
          <CardContent className="p-3 text-xs text-muted-foreground">
            <span className="font-semibold">{node_type}</span> 는 자산 dropdown
            없음 — config_json 에 직접 입력.
          </CardContent>
        </Card>
      );
  }
}

// Phase 8.4 — CDC_EVENT_FETCH 는 Phase 9 정식 구현 예정 (CLAUDE.md 정책: CDC 소스
// 3개 초과 또는 트래픽 500K/일 초과 시 활성화). 현재는 stub 안내.
function CdcStubAsset() {
  return (
    <Card className="border-amber-300 bg-amber-50">
      <CardContent className="space-y-1 p-3 text-xs">
        <div className="flex items-center gap-1 font-semibold text-amber-700">
          <span className="rounded bg-amber-200 px-1.5 py-0.5 text-[10px]">
            STUB
          </span>
          CDC_EVENT_FETCH (Phase 9 예정)
        </div>
        <p className="text-amber-900">
          DB logical replication slot stream 노드. dry-run/실행 시 stub 응답만
          반환합니다. 정식 구현 조건:
        </p>
        <ul className="ml-4 list-disc space-y-0.5 text-[11px] text-amber-900">
          <li>CDC 소스 3개 초과</li>
          <li>또는 일 트래픽 500K rows 초과</li>
        </ul>
        <p className="text-[10px] text-amber-700">
          ※ Canvas 검토용으로만 배치 가능 — 실제 데이터 흐름은 Phase 9.
        </p>
      </CardContent>
    </Card>
  );
}

interface AssetProps {
  config: Record<string, unknown>;
  onPatch: (patch: Record<string, unknown>) => void;
}

function PublicApiFetchAsset({ config, onPatch }: AssetProps) {
  const connectors = useConnectors();
  const current = (config.connector_id as number | undefined) ?? null;
  const selectedConnector = connectors.data?.find(
    (c) => c.connector_id === current,
  );
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="flex items-center justify-between">
          <label className="font-semibold">connector_id</label>
          <Link
            to="/v2/connectors/public-api"
            className="flex items-center gap-1 text-[10px] text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" />새 connector
          </Link>
        </div>
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current ?? ""}
          onChange={(e) =>
            onPatch({
              connector_id: e.target.value ? Number(e.target.value) : null,
            })
          }
        >
          <option value="">선택</option>
          {connectors.data?.map((c) => (
            <option key={c.connector_id} value={c.connector_id}>
              #{c.connector_id} {c.name} [{c.status}]
            </option>
          ))}
        </select>
        {selectedConnector && <AssetStatusBadge status={selectedConnector.status} />}
        {connectors.data?.length === 0 && (
          <p className="text-[10px] text-muted-foreground">
            등록된 connector 가 없습니다. 위 링크로 등록.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// Phase 8.2 — 자산 상태 뱃지 (DRAFT 일 경우 운영 배포 차단 경고).
function AssetStatusBadge({ status }: { status: string }) {
  const isPublished = status === "PUBLISHED";
  const isDraft = status === "DRAFT";
  return (
    <div
      className={
        "rounded-md px-2 py-1 text-[10px] " +
        (isPublished
          ? "bg-green-100 text-green-800"
          : isDraft
            ? "bg-rose-100 text-rose-800 border border-rose-300"
            : "bg-amber-100 text-amber-800")
      }
    >
      <span className="font-semibold">선택된 자산: {status}</span>
      {isDraft && (
        <span className="ml-1">
          ⚠ DRAFT 자산 — 운영 PUBLISH 시 차단됩니다. APPROVED 까지 전이 후 재선택.
        </span>
      )}
      {!isPublished && !isDraft && (
        <span className="ml-1">
          {status} — PUBLISHED 가 아닌 자산은 운영 시 차단될 수 있습니다.
        </span>
      )}
    </div>
  );
}

function MapFieldsAsset({ config, onPatch }: AssetProps) {
  const contracts = useContractsLight();
  const current = (config.contract_id as number | undefined) ?? null;
  const selectedContract = contracts.data?.find(
    (c) => c.contract_id === current,
  );
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="flex items-center justify-between">
          <label className="font-semibold">contract_id (mapping rows source)</label>
          <Link
            to="/v2/mappings/designer"
            className="flex items-center gap-1 text-[10px] text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" />매핑 편집
          </Link>
        </div>
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current ?? ""}
          onChange={(e) =>
            onPatch({
              contract_id: e.target.value ? Number(e.target.value) : null,
            })
          }
        >
          <option value="">선택</option>
          {contracts.data?.map((c) => (
            <option key={c.contract_id} value={c.contract_id}>
              {c.label}
            </option>
          ))}
        </select>
        {selectedContract && (
          <AssetStatusBadge status={selectedContract.status} />
        )}
        <div>
          <label className="mb-1 block font-semibold">source_table</label>
          <Input
            value={(config.source_table as string) ?? ""}
            onChange={(e) => onPatch({ source_table: e.target.value })}
            placeholder="agri_stg.raw_2026_04"
          />
        </div>
        <p className="text-[10px] text-muted-foreground">
          ※ APPROVED/PUBLISHED 매핑만 실행됨. DRAFT 는 dry-run 단계 차단.
        </p>
      </CardContent>
    </Card>
  );
}

function SqlAssetAsset({ config, onPatch }: AssetProps) {
  const assets = useSqlAssets();
  const current = (config.asset_code as string | undefined) ?? "";
  const versions = useMemo(() => {
    if (!current || !assets.data) return [];
    return assets.data.filter((a) => a.asset_code === current);
  }, [current, assets.data]);
  const currentVersion = (config.version as number | undefined) ?? null;
  const selectedAsset = useMemo(() => {
    if (!current || !assets.data) return null;
    if (currentVersion) {
      return (
        assets.data.find(
          (a) => a.asset_code === current && a.version === currentVersion,
        ) ?? null
      );
    }
    // 최신 버전
    return versions[0] ?? null;
  }, [assets.data, current, currentVersion, versions]);

  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="flex items-center justify-between">
          <label className="font-semibold">asset_code</label>
          <Link
            to="/v2/transforms/designer"
            className="flex items-center gap-1 text-[10px] text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" />새 SQL Asset
          </Link>
        </div>
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current}
          onChange={(e) =>
            onPatch({
              asset_code: e.target.value || null,
              version: null,
            })
          }
        >
          <option value="">선택</option>
          {Array.from(
            new Set(assets.data?.map((a) => a.asset_code) ?? []),
          ).map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        {current && versions.length > 0 && (
          <div>
            <label className="mb-1 block font-semibold">version</label>
            <select
              className="h-9 w-full rounded-md border bg-background px-2 text-xs"
              value={(config.version as number | undefined) ?? ""}
              onChange={(e) =>
                onPatch({ version: e.target.value ? Number(e.target.value) : null })
              }
            >
              <option value="">자동 (최신 PUBLISHED)</option>
              {versions.map((a) => (
                <option key={a.asset_id} value={a.version}>
                  v{a.version} [{a.status}]
                </option>
              ))}
            </select>
          </div>
        )}
        {selectedAsset && <AssetStatusBadge status={selectedAsset.status} />}
        <p className="text-[10px] text-muted-foreground">
          ※ APPROVED/PUBLISHED sql_asset 만 실행. DRAFT/REVIEW 는 차단.
        </p>
      </CardContent>
    </Card>
  );
}

function LoadTargetAsset({ config, onPatch }: AssetProps) {
  const policies = useLoadPolicies();
  const current = (config.policy_id as number | undefined) ?? null;
  const selectedPolicy = policies.data?.find((p) => p.policy_id === current);
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="flex items-center justify-between">
          <label className="font-semibold">policy_id (load_policy)</label>
          <Link
            to="/v2/marts/designer"
            className="flex items-center gap-1 text-[10px] text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" />Mart Workbench
          </Link>
        </div>
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current ?? ""}
          onChange={(e) =>
            onPatch({
              policy_id: e.target.value ? Number(e.target.value) : null,
            })
          }
        >
          <option value="">선택</option>
          {policies.data?.map((p) => (
            <option key={p.policy_id} value={p.policy_id}>
              #{p.policy_id} resource={p.resource_id} mode={p.mode} v{p.version}{" "}
              [{p.status}]
            </option>
          ))}
        </select>
        {selectedPolicy && <AssetStatusBadge status={selectedPolicy.status} />}
        <div>
          <label className="mb-1 block font-semibold">source_table</label>
          <Input
            value={(config.source_table as string) ?? ""}
            onChange={(e) => onPatch({ source_table: e.target.value })}
            placeholder="agri_stg.cleaned_2026_04"
          />
        </div>
      </CardContent>
    </Card>
  );
}

interface InboundChannelAssetProps extends AssetProps {
  channelKindFilter: "WEBHOOK" | "FILE_UPLOAD" | "OCR_RESULT" | "CRAWLER_RESULT";
}

function InboundChannelAsset({
  config,
  onPatch,
  channelKindFilter,
}: InboundChannelAssetProps) {
  const channels = useInboundChannels({ channel_kind: channelKindFilter });
  const current = (config.channel_code as string | undefined) ?? "";
  const selectedChannel = channels.data?.find((c) => c.channel_code === current);
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="flex items-center justify-between">
          <label className="font-semibold">channel_code</label>
          <Link
            to="/v2/inbound-channels/designer"
            className="flex items-center gap-1 text-[10px] text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" />새 inbound channel
          </Link>
        </div>
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current}
          onChange={(e) => onPatch({ channel_code: e.target.value || null })}
        >
          <option value="">선택</option>
          {channels.data?.map((c) => (
            <option key={c.channel_id} value={c.channel_code}>
              {c.channel_code} ({c.domain_code}) [{c.status}]
            </option>
          ))}
        </select>
        {selectedChannel && <AssetStatusBadge status={selectedChannel.status} />}
        {channels.data?.length === 0 && (
          <p className="text-[10px] text-muted-foreground">
            등록된 {channelKindFilter} channel 이 없습니다. 위 링크로 등록.
          </p>
        )}
        <div>
          <label className="mb-1 block font-semibold">
            max_envelopes (default 100)
          </label>
          <input
            type="number"
            className="h-8 w-full rounded-md border bg-background px-2 text-xs"
            value={(config.max_envelopes as number | undefined) ?? 100}
            onChange={(e) =>
              onPatch({ max_envelopes: Number(e.target.value) || 100 })
            }
            min={1}
            max={1000}
          />
        </div>
        <p className="text-[10px] text-muted-foreground">
          ※ PUBLISHED + is_active=true channel 의 RECEIVED 상태 envelope 만 처리.
        </p>
      </CardContent>
    </Card>
  );
}

function DbIncrementalAsset({ config, onPatch }: AssetProps) {
  // 기존 v1 ctl.data_source 의 source_code 사용 (v1 설계 화면 그대로).
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="flex items-center justify-between">
          <label className="font-semibold">source_code (ctl.data_source)</label>
          <Link
            to="/sources"
            className="flex items-center gap-1 text-[10px] text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" />legacy Sources
          </Link>
        </div>
        <input
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={(config.source_code as string | undefined) ?? ""}
          onChange={(e) =>
            onPatch({ source_code: e.target.value || null })
          }
          placeholder="e.g. vendor_a_db"
        />
        <div>
          <label className="mb-1 block font-semibold">
            batch_size (default 1000)
          </label>
          <input
            type="number"
            className="h-8 w-full rounded-md border bg-background px-2 text-xs"
            value={(config.batch_size as number | undefined) ?? 1000}
            onChange={(e) =>
              onPatch({ batch_size: Number(e.target.value) || 1000 })
            }
            min={1}
            max={100000}
          />
        </div>
        <p className="text-[10px] text-muted-foreground">
          ※ source_type=DB 이고 is_active=true 인 ctl.data_source 만 가능.
          watermark 기반 incremental + raw_object 적재.
        </p>
      </CardContent>
    </Card>
  );
}

function HttpTransformAsset({ config, onPatch }: AssetProps) {
  const providers = useProviders("HTTP_TRANSFORM");
  const current = (config.provider_code as string | undefined) ?? "";
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="flex items-center justify-between">
          <label className="font-semibold">provider_code</label>
          <Link
            to="/v2/transforms/designer"
            className="flex items-center gap-1 text-[10px] text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" />HTTP Provider 카탈로그
          </Link>
        </div>
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current}
          onChange={(e) => onPatch({ provider_code: e.target.value || null })}
        >
          <option value="">선택</option>
          {providers.data?.map((p) => (
            <option key={p.provider_code} value={p.provider_code}>
              {p.provider_code} [{p.implementation_type}]
            </option>
          ))}
        </select>
        <div>
          <label className="mb-1 block font-semibold">source_table</label>
          <Input
            value={(config.source_table as string) ?? ""}
            onChange={(e) => onPatch({ source_table: e.target.value })}
            placeholder="agri_stg.cleaned_2026_04"
          />
        </div>
        <p className="text-[10px] text-muted-foreground">
          ※ provider 의 secret_ref / config 는 source_provider_binding 가 결정.
        </p>
      </CardContent>
    </Card>
  );
}
