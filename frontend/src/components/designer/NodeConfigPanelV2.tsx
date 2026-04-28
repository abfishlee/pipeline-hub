import { ExternalLink, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { NodeType } from "@/api/pipelines";
import { useConnectors } from "@/api/v2/connectors";
import { useInboundChannels } from "@/api/v2/inbound_channels";
import { useLoadPolicies } from "@/api/v2/load_policies";
import { useContractsLight } from "@/api/v2/mappings";
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

interface AssetProps {
  config: Record<string, unknown>;
  onPatch: (patch: Record<string, unknown>) => void;
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
        <div className="mb-2 text-xs font-semibold uppercase">Node Settings</div>
        <p>Canvas에서 노드를 선택하면 자산과 실행 파라미터를 설정할 수 있습니다.</p>
      </aside>
    );
  }

  const patchConfig = (patch: Record<string, unknown>) => {
    const merged = { ...selected.config_json, ...patch };
    setJsonDraft(JSON.stringify(merged, null, 2));
    onChange({ ...selected, config_json: merged });
  };

  const commitKey = () => {
    const nextKey = keyDraft.trim();
    if (nextKey && nextKey !== selected.node_key) {
      onChange({ ...selected, node_key: nextKey });
    }
  };

  const commitJson = () => {
    try {
      const parsed = jsonDraft.trim() ? JSON.parse(jsonDraft) : {};
      if (typeof parsed !== "object" || parsed == null || Array.isArray(parsed)) {
        setJsonError("config_json must be an object.");
        return;
      }
      setJsonError(null);
      onChange({ ...selected, config_json: parsed as Record<string, unknown> });
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "JSON parse failed");
    }
  };

  return (
    <aside className="flex w-96 shrink-0 flex-col gap-3 overflow-y-auto border-l border-border bg-background p-3">
      <div className="text-xs font-semibold uppercase text-muted-foreground">
        Node Settings · {selected.node_type}
      </div>

      <Card>
        <CardContent className="space-y-3 p-3 text-xs">
          <label className="block space-y-1 font-semibold">
            node_type
            <div className="rounded-md border border-input bg-muted/40 px-3 py-2 font-mono">
              {selected.node_type}
            </div>
          </label>
          <label className="block space-y-1 font-semibold">
            node_key
            <Input
              value={keyDraft}
              onChange={(e) => setKeyDraft(e.target.value)}
              onBlur={commitKey}
              className="h-9 font-mono text-xs"
              placeholder="clean_price"
            />
          </label>
        </CardContent>
      </Card>

      <AssetSection
        nodeType={selected.node_type}
        config={selected.config_json}
        onPatch={patchConfig}
      />

      <details className="rounded-md border border-border bg-background text-xs">
        <summary className="cursor-pointer px-3 py-2 font-semibold text-muted-foreground hover:bg-secondary">
          Advanced config JSON
        </summary>
        <div className="space-y-2 px-3 pb-3 pt-2">
          <div className="flex justify-end">
            <Button variant="ghost" size="sm" onClick={commitJson} className="h-7 text-xs">
              <Save className="h-3 w-3" />
              적용
            </Button>
          </div>
          <textarea
            value={jsonDraft}
            onChange={(e) => setJsonDraft(e.target.value)}
            spellCheck={false}
            className="h-44 w-full resize-none rounded-md border border-input bg-background p-2 font-mono text-[11px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {jsonError && <p className="text-[11px] text-rose-600">{jsonError}</p>}
        </div>
      </details>

      {onDelete && (
        <Button variant="destructive" size="sm" onClick={onDelete}>
          <Trash2 className="h-4 w-4" />
          노드 삭제
        </Button>
      )}
    </aside>
  );
}

function AssetSection({
  nodeType,
  config,
  onPatch,
}: {
  nodeType: NodeType;
  config: Record<string, unknown>;
  onPatch: (patch: Record<string, unknown>) => void;
}) {
  switch (nodeType) {
    case "PUBLIC_API_FETCH":
      return <PublicApiFetchAsset config={config} onPatch={onPatch} />;
    case "MAP_FIELDS":
      return <MapFieldsAsset config={config} onPatch={onPatch} />;
    case "SQL_ASSET_TRANSFORM":
      return <SqlAssetAsset config={config} onPatch={onPatch} />;
    case "SQL_INLINE_TRANSFORM":
      return <SqlInlineAsset config={config} onPatch={onPatch} />;
    case "LOAD_TARGET":
      return <LoadTargetAsset config={config} onPatch={onPatch} />;
    case "WEBHOOK_INGEST":
      return <InboundChannelAsset config={config} onPatch={onPatch} channelKind="WEBHOOK" />;
    case "FILE_UPLOAD_INGEST":
      return <InboundChannelAsset config={config} onPatch={onPatch} channelKind="FILE_UPLOAD" />;
    case "OCR_RESULT_INGEST":
      return <InboundChannelAsset config={config} onPatch={onPatch} channelKind="OCR_RESULT" />;
    case "CRAWLER_RESULT_INGEST":
      return <InboundChannelAsset config={config} onPatch={onPatch} channelKind="CRAWLER_RESULT" />;
    case "DB_INCREMENTAL_FETCH":
      return <SimpleField title="DB incremental" name="source_code" config={config} onPatch={onPatch} />;
    default:
      return (
        <Card>
          <CardContent className="space-y-2 p-3 text-xs text-muted-foreground">
            <div className="font-semibold text-foreground">No dedicated form</div>
            이 노드는 Advanced config JSON에서 직접 설정합니다.
          </CardContent>
        </Card>
      );
  }
}

function AssetStatusBadge({ status }: { status: string }) {
  const tone =
    status === "PUBLISHED"
      ? "bg-green-100 text-green-800"
      : status === "DRAFT"
        ? "bg-rose-100 text-rose-800 border border-rose-300"
        : "bg-amber-100 text-amber-800";
  return (
    <div className={`rounded-md px-2 py-1 text-[10px] ${tone}`}>
      선택한 자산 상태: <span className="font-semibold">{status}</span>
    </div>
  );
}

function PublicApiFetchAsset({ config, onPatch }: AssetProps) {
  const connectors = useConnectors();
  const current = (config.connector_id as number | undefined) ?? null;
  const selected = connectors.data?.find((c) => c.connector_id === current);
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <LinkHeader label="connector_id" to="/v2/connectors/public-api" text="API Pull" />
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current ?? ""}
          onChange={(e) => onPatch({ connector_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">선택</option>
          {connectors.data?.map((c) => (
            <option key={c.connector_id} value={c.connector_id}>
              #{c.connector_id} {c.name} [{c.status}]
            </option>
          ))}
        </select>
        {selected && <AssetStatusBadge status={selected.status} />}
      </CardContent>
    </Card>
  );
}

function MapFieldsAsset({ config, onPatch }: AssetProps) {
  const contracts = useContractsLight();
  const current = (config.contract_id as number | undefined) ?? null;
  const selected = contracts.data?.find((c) => c.contract_id === current);
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <LinkHeader label="contract_id" to="/v2/mappings/designer" text="Field Mapping" />
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current ?? ""}
          onChange={(e) => onPatch({ contract_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">선택</option>
          {contracts.data?.map((c) => (
            <option key={c.contract_id} value={c.contract_id}>
              {c.label}
            </option>
          ))}
        </select>
        {selected && <AssetStatusBadge status={selected.status} />}
        <label className="block space-y-1 font-semibold">
          source_table
          <Input
            value={(config.source_table as string) ?? ""}
            onChange={(e) => onPatch({ source_table: e.target.value || null })}
            placeholder="선행 노드 자동 주입은 다음 단계에서 사용, 현재는 명시 입력"
          />
        </label>
        <label className="block space-y-1 font-semibold">
          target_table override
          <Input
            value={(config.target_table as string) ?? ""}
            onChange={(e) => onPatch({ target_table: e.target.value || null })}
            placeholder="비우면 mapping 기본 target 또는 wf.tmp_run_*"
          />
        </label>
      </CardContent>
    </Card>
  );
}

function SqlAssetAsset({ config, onPatch }: AssetProps) {
  const assets = useSqlAssets();
  const current = (config.asset_code as string | undefined) ?? "";
  const versions = useMemo(() => {
    if (!current || !assets.data) return [];
    return assets.data
      .filter((a) => a.asset_code === current)
      .sort((a, b) => b.version - a.version);
  }, [assets.data, current]);
  const currentVersion = (config.version as number | undefined) ?? null;
  const selected = currentVersion
    ? versions.find((a) => a.version === currentVersion)
    : versions[0];
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <LinkHeader label="SQL Studio asset" to="/v2/transforms/designer" text="SQL Studio" />
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current}
          onChange={(e) => onPatch({ asset_code: e.target.value || null, version: null })}
        >
          <option value="">선택</option>
          {Array.from(new Set(assets.data?.map((a) => a.asset_code) ?? [])).map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
        {versions.length > 0 && (
          <select
            className="h-9 w-full rounded-md border bg-background px-2 text-xs"
            value={(config.version as number | undefined) ?? ""}
            onChange={(e) => onPatch({ version: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">자동 (최신 APPROVED/PUBLISHED)</option>
            {versions.map((a) => (
              <option key={a.asset_id} value={a.version}>
                v{a.version} · {a.asset_type} [{a.status}]
              </option>
            ))}
          </select>
        )}
        {selected && (
          <>
            <AssetStatusBadge status={selected.status} />
            <div className="rounded-md bg-muted/40 p-2 text-[10px] text-muted-foreground">
              type: <span className="font-semibold text-foreground">{selected.asset_type}</span>
              <br />
              default output:{" "}
              <span className="font-mono">{selected.output_table || "wf.tmp_run_* / script"}</span>
            </div>
          </>
        )}
        <label className="block space-y-1 font-semibold">
          input_from
          <Input
            value={(config.input_from as string) ?? ""}
            onChange={(e) => onPatch({ input_from: e.target.value || null })}
            placeholder="비우면 첫 번째 선행 노드 output 사용"
          />
        </label>
        <label className="block space-y-1 font-semibold">
          output_table override
          <Input
            value={(config.output_table as string) ?? ""}
            onChange={(e) => onPatch({ output_table: e.target.value || null })}
            placeholder="비우면 SQL 자산 기본값 또는 wf.tmp_run_*"
          />
        </label>
        <p className="text-[10px] text-muted-foreground">
          SQL의 {"{{input_table}}"}은 선행 노드 output table로 자동 치환됩니다.
        </p>
      </CardContent>
    </Card>
  );
}

function SqlInlineAsset({ config, onPatch }: AssetProps) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="font-semibold">Inline SQL</div>
        <textarea
          value={(config.sql as string) ?? ""}
          onChange={(e) => onPatch({ sql: e.target.value })}
          spellCheck={false}
          className="h-56 w-full resize-y rounded-md border bg-background p-2 font-mono text-[11px]"
          placeholder={"SELECT *\nFROM {{input_table}}"}
        />
        <Input
          value={(config.input_from as string) ?? ""}
          onChange={(e) => onPatch({ input_from: e.target.value || null })}
          placeholder="input_from (optional)"
        />
        <Input
          value={(config.output_table as string) ?? ""}
          onChange={(e) => onPatch({ output_table: e.target.value || null })}
          placeholder="output_table override (optional)"
        />
      </CardContent>
    </Card>
  );
}

function LoadTargetAsset({ config, onPatch }: AssetProps) {
  const policies = useLoadPolicies();
  const current = (config.policy_id as number | undefined) ?? null;
  const selected = policies.data?.find((p) => p.policy_id === current);
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <LinkHeader label="policy_id" to="/v2/marts/designer" text="Mart Designer" />
        <select
          className="h-9 w-full rounded-md border bg-background px-2 text-xs"
          value={current ?? ""}
          onChange={(e) => onPatch({ policy_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">선택</option>
          {policies.data?.map((p) => (
            <option key={p.policy_id} value={p.policy_id}>
              #{p.policy_id} resource={p.resource_id} {p.mode} [{p.status}]
            </option>
          ))}
        </select>
        {selected && <AssetStatusBadge status={selected.status} />}
        <Input
          value={(config.source_table as string) ?? ""}
          onChange={(e) => onPatch({ source_table: e.target.value || null })}
          placeholder="source_table"
        />
      </CardContent>
    </Card>
  );
}

function InboundChannelAsset({
  config,
  onPatch,
  channelKind,
}: AssetProps & { channelKind: "WEBHOOK" | "FILE_UPLOAD" | "OCR_RESULT" | "CRAWLER_RESULT" }) {
  const channels = useInboundChannels({ channel_kind: channelKind });
  const current = (config.channel_code as string | undefined) ?? "";
  const selected = channels.data?.find((c) => c.channel_code === current);
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <LinkHeader label="channel_code" to="/v2/inbound-channels/designer" text="Inbound Push" />
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
        {selected && <AssetStatusBadge status={selected.status} />}
        <Input
          type="number"
          value={(config.max_envelopes as number | undefined) ?? 100}
          onChange={(e) => onPatch({ max_envelopes: Number(e.target.value) || 100 })}
          placeholder="max_envelopes"
        />
      </CardContent>
    </Card>
  );
}

function SimpleField({ title, name, config, onPatch }: AssetProps & { title: string; name: string }) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="font-semibold">{title}</div>
        <Input
          value={(config[name] as string) ?? ""}
          onChange={(e) => onPatch({ [name]: e.target.value || null })}
          placeholder={name}
        />
      </CardContent>
    </Card>
  );
}

function LinkHeader({ label, to, text }: { label: string; to: string; text: string }) {
  return (
    <div className="flex items-center justify-between">
      <label className="font-semibold">{label}</label>
      <Link to={to} className="flex items-center gap-1 text-[10px] text-primary hover:underline">
        <ExternalLink className="h-3 w-3" />
        {text}
      </Link>
    </div>
  );
}
