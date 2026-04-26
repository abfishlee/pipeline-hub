import { Copy, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  type ApiKeyCreated,
  type ApiKeyOut,
  type PublicApiScope,
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
} from "@/api/api_keys";
import { ApiError } from "@/api/client";
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
import { formatDateTime } from "@/lib/format";

const ALL_SCOPES: PublicApiScope[] = [
  "prices.read",
  "products.read",
  "aggregates.read",
];

export function ApiKeysPage() {
  const keys = useApiKeys();
  const [creating, setCreating] = useState(false);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">API Keys</h1>
        <Button onClick={() => setCreating(true)}>
          <Plus className="mr-1 h-4 w-4" />
          새 키 발급
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {keys.isLoading && <div className="p-4 text-sm">불러오는 중…</div>}
          {keys.data && (
            <Table>
              <Thead>
                <Tr>
                  <Th>ID</Th>
                  <Th>prefix</Th>
                  <Th>client</Th>
                  <Th>scope</Th>
                  <Th>retailers</Th>
                  <Th>rate</Th>
                  <Th>state</Th>
                  <Th>last_used</Th>
                  <Th>expires</Th>
                  <Th></Th>
                </Tr>
              </Thead>
              <Tbody>
                {keys.data.map((k) => (
                  <ApiKeyRow key={k.api_key_id} k={k} />
                ))}
                {keys.data.length === 0 && (
                  <Tr>
                    <Td colSpan={10} className="text-center text-muted-foreground">
                      발급된 키가 없습니다.
                    </Td>
                  </Tr>
                )}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <CreateDialog
        open={creating}
        onOpenChange={(o) => !o && setCreating(false)}
        onCreated={(c) => {
          setCreating(false);
          setCreatedKey(c);
        }}
      />
      <CreatedKeyDialog
        created={createdKey}
        onClose={() => setCreatedKey(null)}
      />
    </div>
  );
}

function ApiKeyRow({ k }: { k: ApiKeyOut }) {
  const revoke = useRevokeApiKey();
  return (
    <Tr>
      <Td className="font-mono text-xs">{k.api_key_id}</Td>
      <Td className="font-mono">{k.key_prefix}</Td>
      <Td>{k.client_name}</Td>
      <Td className="text-xs">{k.scope.join(", ") || "-"}</Td>
      <Td className="text-xs">{k.retailer_allowlist.join(",") || "-"}</Td>
      <Td className="font-mono text-xs">{k.rate_limit_per_min}/min</Td>
      <Td>
        {k.revoked_at ? (
          <Badge variant="destructive">revoked</Badge>
        ) : k.is_active ? (
          <Badge variant="success">active</Badge>
        ) : (
          <Badge variant="muted">inactive</Badge>
        )}
      </Td>
      <Td className="text-xs">
        {k.last_used_at ? formatDateTime(k.last_used_at) : "-"}
      </Td>
      <Td className="text-xs">
        {k.expires_at ? formatDateTime(k.expires_at) : "-"}
      </Td>
      <Td>
        {!k.revoked_at && (
          <Button
            variant="ghost"
            size="icon"
            disabled={revoke.isPending}
            onClick={() => {
              if (!confirm(`${k.key_prefix} 키를 폐기하시겠습니까?`)) return;
              revoke.mutate(k.api_key_id, {
                onSuccess: () => toast.success("폐기됨"),
                onError: (err) =>
                  toast.error(err instanceof ApiError ? err.message : "실패"),
              });
            }}
          >
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        )}
      </Td>
    </Tr>
  );
}

function CreateDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (k: ApiKeyCreated) => void;
}) {
  const [clientName, setClientName] = useState("");
  const [scope, setScope] = useState<PublicApiScope[]>([]);
  const [allowlist, setAllowlist] = useState("");
  const [rate, setRate] = useState(60);
  const [expires, setExpires] = useState("");
  const create = useCreateApiKey();

  function reset() {
    setClientName("");
    setScope([]);
    setAllowlist("");
    setRate(60);
    setExpires("");
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>API Key 발급</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <FormRow label="client_name (외부 사용처 식별)">
            <Input
              value={clientName}
              onChange={(e) => setClientName(e.target.value)}
              placeholder="예: 마트A 가격조회"
            />
          </FormRow>
          <FormRow label="scope">
            <div className="flex flex-col gap-1">
              {ALL_SCOPES.map((s) => (
                <label key={s} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={scope.includes(s)}
                    onChange={(e) => {
                      if (e.target.checked) setScope([...scope, s]);
                      else setScope(scope.filter((x) => x !== s));
                    }}
                  />
                  <code className="font-mono">{s}</code>
                </label>
              ))}
            </div>
          </FormRow>
          <FormRow label="retailer_allowlist (콤마 구분 retailer_id)">
            <Input
              value={allowlist}
              onChange={(e) => setAllowlist(e.target.value)}
              placeholder="예: 1,3,7"
            />
            <p className="text-xs text-muted-foreground">
              비워 두면 모든 retailer 의 row 가 RLS 로 차단됩니다.
            </p>
          </FormRow>
          <FormRow label="rate_limit_per_min">
            <Input
              type="number"
              min={1}
              max={100000}
              value={rate}
              onChange={(e) => setRate(Number(e.target.value) || 0)}
            />
          </FormRow>
          <FormRow label="expires_at (선택)">
            <Input
              type="date"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
            />
          </FormRow>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            취소
          </Button>
          <Button
            disabled={create.isPending || !clientName || scope.length === 0}
            onClick={() => {
              const allow = allowlist
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
                .map(Number)
                .filter((n) => Number.isFinite(n));
              create.mutate(
                {
                  client_name: clientName,
                  scope,
                  retailer_allowlist: allow,
                  rate_limit_per_min: rate,
                  expires_at: expires
                    ? new Date(expires).toISOString()
                    : null,
                },
                {
                  onSuccess: (data) => {
                    toast.success("발급되었습니다 — 평문 secret 1회만 노출");
                    reset();
                    onCreated(data);
                  },
                  onError: (err) =>
                    toast.error(
                      err instanceof ApiError ? err.message : "발급 실패",
                    ),
                },
              );
            }}
          >
            {create.isPending ? "발급 중…" : "발급"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CreatedKeyDialog({
  created,
  onClose,
}: {
  created: ApiKeyCreated | null;
  onClose: () => void;
}) {
  if (!created) return null;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>발급 완료 — secret 1회 노출</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <p className="text-rose-600">
            이 화면을 닫으면 다시 볼 수 없습니다. 안전한 곳에 즉시 복사하세요.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 break-all rounded-md bg-muted p-2 font-mono text-xs">
              {created.secret}
            </code>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(created.secret);
                toast.success("복사됨");
              }}
            >
              <Copy className="mr-1 h-3 w-3" />
              복사
            </Button>
          </div>
          <ul className="text-xs text-muted-foreground">
            <li>prefix: <code className="font-mono">{created.key_prefix}</code></li>
            <li>scope: <code className="font-mono">{created.scope.join(", ")}</code></li>
            <li>rate_limit: {created.rate_limit_per_min} req/min</li>
          </ul>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>닫기</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FormRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
    </div>
  );
}
