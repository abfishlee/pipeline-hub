import { Plus } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { type UserCreate, useCreateUser, useUsers } from "@/api/users";
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

const ROLES = ["ADMIN", "OPERATOR", "REVIEWER", "APPROVER", "VIEWER"];

export function UsersPage() {
  const users = useUsers({ limit: 100 });
  const [creating, setCreating] = useState(false);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          ADMIN 전용 — 사용자 생성/조회. 비밀번호 변경/역할 변경은 추후.
        </p>
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" />
          새 사용자
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {users.isLoading && <div className="p-4 text-sm">불러오는 중...</div>}
          {users.data && (
            <Table>
              <Thead>
                <Tr>
                  <Th>ID</Th>
                  <Th>로그인</Th>
                  <Th>이름</Th>
                  <Th>이메일</Th>
                  <Th>역할</Th>
                  <Th>활성</Th>
                  <Th>생성일</Th>
                </Tr>
              </Thead>
              <Tbody>
                {users.data.map((u) => (
                  <Tr key={u.user_id}>
                    <Td className="font-mono text-xs">{u.user_id}</Td>
                    <Td className="font-mono">{u.login_id}</Td>
                    <Td>{u.display_name}</Td>
                    <Td className="text-xs">{u.email ?? "-"}</Td>
                    <Td className="space-x-1">
                      {u.roles.map((r) => (
                        <Badge key={r} variant="secondary">
                          {r}
                        </Badge>
                      ))}
                    </Td>
                    <Td>
                      {u.is_active ? (
                        <Badge variant="success">활성</Badge>
                      ) : (
                        <Badge variant="muted">비활성</Badge>
                      )}
                    </Td>
                    <Td className="text-xs">{formatDateTime(u.created_at)}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>

      <CreateDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

function CreateDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [form, setForm] = useState<UserCreate>({
    login_id: "",
    display_name: "",
    password: "",
    role_codes: ["VIEWER"],
  });
  const create = useCreateUser();

  function reset() {
    setForm({
      login_id: "",
      display_name: "",
      password: "",
      role_codes: ["VIEWER"],
    });
  }

  function toggleRole(role: string) {
    setForm((f) => {
      const has = f.role_codes?.includes(role) ?? false;
      const next = has
        ? (f.role_codes ?? []).filter((r) => r !== role)
        : [...(f.role_codes ?? []), role];
      return { ...f, role_codes: next };
    });
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
          <DialogTitle>새 사용자 등록</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <FormRow label="login_id (3~64자, 영숫자_.-)">
            <Input
              value={form.login_id}
              onChange={(e) =>
                setForm((f) => ({ ...f, login_id: e.target.value }))
              }
            />
          </FormRow>
          <FormRow label="이름">
            <Input
              value={form.display_name}
              onChange={(e) =>
                setForm((f) => ({ ...f, display_name: e.target.value }))
              }
            />
          </FormRow>
          <FormRow label="이메일 (선택)">
            <Input
              type="email"
              value={form.email ?? ""}
              onChange={(e) =>
                setForm((f) => ({ ...f, email: e.target.value || null }))
              }
            />
          </FormRow>
          <FormRow label="비밀번호 (8자 이상)">
            <Input
              type="password"
              value={form.password}
              onChange={(e) =>
                setForm((f) => ({ ...f, password: e.target.value }))
              }
            />
          </FormRow>
          <FormRow label="역할">
            <div className="flex flex-wrap gap-2">
              {ROLES.map((r) => {
                const active = form.role_codes?.includes(r);
                return (
                  <Button
                    key={r}
                    type="button"
                    variant={active ? "default" : "outline"}
                    size="sm"
                    onClick={() => toggleRole(r)}
                  >
                    {r}
                  </Button>
                );
              })}
            </div>
          </FormRow>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            취소
          </Button>
          <Button
            disabled={create.isPending}
            onClick={() => {
              create.mutate(form, {
                onSuccess: () => {
                  toast.success("사용자 생성 완료");
                  reset();
                  onOpenChange(false);
                },
                onError: (err) =>
                  toast.error(
                    err instanceof ApiError ? err.message : "생성 실패",
                  ),
              });
            }}
          >
            생성
          </Button>
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
