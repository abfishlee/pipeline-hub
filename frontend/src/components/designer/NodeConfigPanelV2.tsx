import { ExternalLink, Save, Trash2 } from "lucide-react";
import type React from "react";
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
        <p>Select a Canvas node to configure assets, input source, and runtime parameters.</p>
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
        Node Settings - {selected.node_type}
      </div>

      <Card>
        <CardContent className="space-y-3 p-3 text-xs">
          <FieldLabel label="node_type">
            <div className="rounded-md border border-input bg-muted/40 px-3 py-2 font-mono">
              {selected.node_type}
            </div>
          </FieldLabel>
          <FieldLabel label="node_key">
            <Input
              value={keyDraft}
              onChange={(e) => setKeyDraft(e.target.value)}
              onBlur={commitKey}
              className="h-9 font-mono text-xs"
              placeholder="clean_price"
            />
          </FieldLabel>
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
              Apply
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
          Delete node
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
      return <DbIncrementalAsset config={config} onPatch={onPatch} />;
    default:
      return (
        <Card>
          <CardContent className="space-y-2 p-3 text-xs text-muted-foreground">
            <div className="font-semibold text-foreground">No dedicated form</div>
            Use Advanced config JSON for this node.
          </CardContent>
        </Card>
      );
  }
}

function PublicApiFetchAsset({ config, onPatch }: AssetProps) {
  const connectors = useConnectors();
  const current = (config.connector_id as number | undefined) ?? null;
  const selected = connectors.data?.find((c) => c.connector_id === current);
  return (
    <NodeCard title="API Pull">
      <LinkHeader label="connector_id" to="/v2/connectors/public-api" text="Manage APIs" />
      <select
        className="h-9 w-full rounded-md border bg-background px-2 text-xs"
        value={current ?? ""}
        onChange={(e) => onPatch({ connector_id: e.target.value ? Number(e.target.value) : null })}
      >
        <option value="">Select connector</option>
        {connectors.data?.map((c) => (
          <option key={c.connector_id} value={c.connector_id}>
            #{c.connector_id} {c.name} [{c.status}]
          </option>
        ))}
      </select>
      {selected && <AssetStatusBadge status={selected.status} />}
      <NumberInput
        label="max_pages"
        value={(config.max_pages as number | undefined) ?? 10}
        min={1}
        max={100}
        onChange={(value) => onPatch({ max_pages: value })}
      />
      <TextInput
        label="output_table override"
        value={(config.output_table as string) ?? ""}
        placeholder="empty -> wf.tmp_run_*"
        onChange={(value) => onPatch({ output_table: value || null })}
      />
      <JsonTextArea
        label="runtime_params"
        value={config.runtime_params}
        placeholder={'{\n  "page": 1\n}'}
        onChange={(value) => onPatch({ runtime_params: value })}
      />
    </NodeCard>
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
    <NodeCard title={`${channelKind} ingest`}>
      <LinkHeader label="channel_code" to="/v2/inbound-channels/designer" text="Manage channels" />
      <select
        className="h-9 w-full rounded-md border bg-background px-2 text-xs"
        value={current}
        onChange={(e) => onPatch({ channel_code: e.target.value || null })}
      >
        <option value="">Select channel</option>
        {channels.data?.map((c) => (
          <option key={c.channel_id} value={c.channel_code}>
            {c.channel_code} ({c.domain_code}) [{c.status}]
          </option>
        ))}
      </select>
      {selected && <AssetStatusBadge status={selected.status} />}
      <NumberInput
        label="max_envelopes"
        value={(config.max_envelopes as number | undefined) ?? 100}
        min={1}
        max={1000}
        onChange={(value) => onPatch({ max_envelopes: value })}
      />
      <TextInput
        label="envelope_id"
        value={String((config.envelope_id as number | string | undefined) ?? "")}
        placeholder="optional single envelope id"
        onChange={(value) => onPatch({ envelope_id: value ? Number(value) : null })}
      />
      <TextInput
        label="payload_path"
        value={(config.payload_path as string) ?? ""}
        placeholder="optional JSON path, e.g. items"
        onChange={(value) => onPatch({ payload_path: value || null })}
      />
      <TextInput
        label="output_table override"
        value={(config.output_table as string) ?? ""}
        placeholder="empty -> wf.tmp_run_*"
        onChange={(value) => onPatch({ output_table: value || null })}
      />
    </NodeCard>
  );
}

function MapFieldsAsset({ config, onPatch }: AssetProps) {
  const contracts = useContractsLight();
  const current = (config.contract_id as number | undefined) ?? null;
  const selected = contracts.data?.find((c) => c.contract_id === current);
  return (
    <NodeCard title="Field Mapping">
      <LinkHeader label="contract_id" to="/v2/mappings/designer" text="Manage mappings" />
      <select
        className="h-9 w-full rounded-md border bg-background px-2 text-xs"
        value={current ?? ""}
        onChange={(e) => onPatch({ contract_id: e.target.value ? Number(e.target.value) : null })}
      >
        <option value="">Select contract</option>
        {contracts.data?.map((c) => (
          <option key={c.contract_id} value={c.contract_id}>
            {c.label}
          </option>
        ))}
      </select>
      {selected && <AssetStatusBadge status={selected.status} />}
      <TextInput
        label="input_from"
        value={(config.input_from as string) ?? ""}
        placeholder="empty -> first upstream output"
        onChange={(value) => onPatch({ input_from: value || null })}
      />
      <TextInput
        label="source_table override"
        value={(config.source_table as string) ?? ""}
        placeholder="optional; otherwise upstream output_table"
        onChange={(value) => onPatch({ source_table: value || null })}
      />
      <TextInput
        label="target_table override"
        value={(config.target_table as string) ?? ""}
        placeholder="empty -> mapping default or wf.tmp_run_*"
        onChange={(value) => onPatch({ target_table: value || null })}
      />
      <NumberInput
        label="limit_rows"
        value={(config.limit_rows as number | undefined) ?? 100000}
        min={1}
        max={10000000}
        onChange={(value) => onPatch({ limit_rows: value })}
      />
    </NodeCard>
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
    <NodeCard title="SQL Studio Asset">
      <LinkHeader label="asset_code" to="/v2/transforms/designer" text="SQL Studio" />
      <select
        className="h-9 w-full rounded-md border bg-background px-2 text-xs"
        value={current}
        onChange={(e) => onPatch({ asset_code: e.target.value || null, version: null })}
      >
        <option value="">Select SQL asset</option>
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
          <option value="">Auto latest APPROVED/PUBLISHED</option>
          {versions.map((a) => (
            <option key={a.asset_id} value={a.version}>
              v{a.version} - {a.asset_type} [{a.status}]
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
      <TextInput
        label="input_from"
        value={(config.input_from as string) ?? ""}
        placeholder="empty -> first upstream output"
        onChange={(value) => onPatch({ input_from: value || null })}
      />
      <TextInput
        label="input_table override"
        value={(config.input_table as string) ?? ""}
        placeholder="optional; otherwise upstream output_table"
        onChange={(value) => onPatch({ input_table: value || null })}
      />
      <TextInput
        label="output_table override"
        value={(config.output_table as string) ?? ""}
        placeholder="empty -> asset default or wf.tmp_run_*"
        onChange={(value) => onPatch({ output_table: value || null })}
      />
      <p className="text-[10px] text-muted-foreground">
        SQL templates can use {"{{input_table}}"}, {"{{output_table}}"}, {"{{run_id}}"}, and {"{{domain_code}}"}.
      </p>
    </NodeCard>
  );
}

function SqlInlineAsset({ config, onPatch }: AssetProps) {
  return (
    <NodeCard title="Inline SQL">
      <textarea
        value={(config.sql as string) ?? ""}
        onChange={(e) => onPatch({ sql: e.target.value })}
        spellCheck={false}
        className="h-56 w-full resize-y rounded-md border bg-background p-2 font-mono text-[11px]"
        placeholder={"SELECT *\nFROM {{input_table}}"}
      />
      <TextInput
        label="input_from"
        value={(config.input_from as string) ?? ""}
        placeholder="empty -> first upstream output"
        onChange={(value) => onPatch({ input_from: value || null })}
      />
      <TextInput
        label="input_table override"
        value={(config.input_table as string) ?? ""}
        placeholder="optional; otherwise upstream output_table"
        onChange={(value) => onPatch({ input_table: value || null })}
      />
      <TextInput
        label="output_table override"
        value={(config.output_table as string) ?? ""}
        placeholder="empty -> wf.tmp_run_*"
        onChange={(value) => onPatch({ output_table: value || null })}
      />
    </NodeCard>
  );
}

function LoadTargetAsset({ config, onPatch }: AssetProps) {
  const policies = useLoadPolicies();
  const current = (config.policy_id as number | undefined) ?? null;
  const selected = policies.data?.find((p) => p.policy_id === current);
  return (
    <NodeCard title="Load Target">
      <LinkHeader label="policy_id" to="/v2/marts/designer" text="Mart Designer" />
      <select
        className="h-9 w-full rounded-md border bg-background px-2 text-xs"
        value={current ?? ""}
        onChange={(e) => onPatch({ policy_id: e.target.value ? Number(e.target.value) : null })}
      >
        <option value="">Select load policy</option>
        {policies.data?.map((p) => (
          <option key={p.policy_id} value={p.policy_id}>
            #{p.policy_id} resource={p.resource_id} {p.mode} [{p.status}]
          </option>
        ))}
      </select>
      {selected && <AssetStatusBadge status={selected.status} />}
      <TextInput
        label="input_from"
        value={(config.input_from as string) ?? ""}
        placeholder="empty -> first upstream output"
        onChange={(value) => onPatch({ input_from: value || null })}
      />
      <TextInput
        label="source_table override"
        value={(config.source_table as string) ?? ""}
        placeholder="optional; otherwise upstream output_table"
        onChange={(value) => onPatch({ source_table: value || null })}
      />
      <TextInput
        label="target_table override"
        value={(config.target_table as string) ?? ""}
        placeholder="optional; otherwise policy/resource target"
        onChange={(value) => onPatch({ target_table: value || null })}
      />
    </NodeCard>
  );
}

function DbIncrementalAsset({ config, onPatch }: AssetProps) {
  return (
    <NodeCard title="DB Incremental">
      <TextInput
        label="source_code"
        value={(config.source_code as string) ?? ""}
        placeholder="registered DB source_code"
        onChange={(value) => onPatch({ source_code: value || null })}
      />
      <NumberInput
        label="batch_size"
        value={(config.batch_size as number | undefined) ?? 1000}
        min={1}
        max={100000}
        onChange={(value) => onPatch({ batch_size: value })}
      />
      <TextInput
        label="output_table override"
        value={(config.output_table as string) ?? ""}
        placeholder="empty -> wf.tmp_run_*"
        onChange={(value) => onPatch({ output_table: value || null })}
      />
    </NodeCard>
  );
}

function NodeCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="space-y-2 p-3 text-xs">
        <div className="font-semibold text-foreground">{title}</div>
        {children}
      </CardContent>
    </Card>
  );
}

function FieldLabel({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1 font-semibold">
      {label}
      {children}
    </label>
  );
}

function TextInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}) {
  return (
    <FieldLabel label={label}>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </FieldLabel>
  );
}

function NumberInput({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <FieldLabel label={label}>
      <Input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value) || min)}
      />
    </FieldLabel>
  );
}

function JsonTextArea({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: unknown;
  placeholder?: string;
  onChange: (value: Record<string, unknown>) => void;
}) {
  const [draft, setDraft] = useState(() =>
    value ? JSON.stringify(value, null, 2) : "",
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(value ? JSON.stringify(value, null, 2) : "");
    setError(null);
  }, [value]);

  const commit = () => {
    if (!draft.trim()) {
      setError(null);
      onChange({});
      return;
    }
    try {
      const parsed = JSON.parse(draft);
      if (typeof parsed !== "object" || parsed == null || Array.isArray(parsed)) {
        setError("Must be a JSON object.");
        return;
      }
      setError(null);
      onChange(parsed as Record<string, unknown>);
    } catch (e) {
      setError(e instanceof Error ? e.message : "JSON parse failed");
    }
  };

  return (
    <FieldLabel label={label}>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        spellCheck={false}
        className="h-24 w-full resize-y rounded-md border bg-background p-2 font-mono text-[11px]"
        placeholder={placeholder}
      />
      {error && <p className="text-[10px] text-rose-600">{error}</p>}
    </FieldLabel>
  );
}

function AssetStatusBadge({ status }: { status: string }) {
  const tone =
    status === "PUBLISHED"
      ? "bg-green-100 text-green-800"
      : status === "DRAFT"
        ? "border border-rose-300 bg-rose-100 text-rose-800"
        : "bg-amber-100 text-amber-800";
  return (
    <div className={`rounded-md px-2 py-1 text-[10px] ${tone}`}>
      Asset status: <span className="font-semibold">{status}</span>
    </div>
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
