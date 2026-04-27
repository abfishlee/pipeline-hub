import { Server } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useLogin, useMe } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuthStore } from "@/store/auth";

export function LoginPage() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const navigate = useNavigate();
  const login = useLogin();
  const me = useMe(false);

  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");

  // 이미 로그인 상태면 / 로 리다이렉트
  if (accessToken) {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!loginId.trim() || !password) {
      toast.error("아이디와 비밀번호를 입력하세요.");
      return;
    }
    try {
      await login.mutateAsync({ login_id: loginId.trim(), password });
      // /me 호출 → 사용자 정보(역할) 동기화 후 대시보드로.
      await me.refetch();
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        toast.error(err.message);
      } else {
        toast.error("로그인에 실패했습니다.");
      }
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-secondary/30 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="border-b-0 text-center">
          <div className="mb-4 flex justify-center">
            <div className="rounded-full bg-primary/10 p-3">
              <Server className="h-7 w-7 text-primary" />
            </div>
          </div>
          <CardTitle className="text-xl">Pipeline Hub</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">
            공용 데이터 수집 파이프라인 플랫폼
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="login_id" className="text-sm font-medium">
                아이디
              </label>
              <Input
                id="login_id"
                autoComplete="username"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
                placeholder="예: it_admin"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="password" className="text-sm font-medium">
                비밀번호
              </label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={login.isPending}
            >
              {login.isPending ? "로그인 중..." : "로그인"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
