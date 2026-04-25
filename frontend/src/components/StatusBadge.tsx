import { Badge } from "@/components/ui/badge";

const STATUS_VARIANT: Record<string, "default" | "success" | "warning" | "destructive" | "muted"> = {
  PENDING: "muted",
  RUNNING: "default",
  SUCCESS: "success",
  FAILED: "destructive",
  CANCELLED: "muted",
  RECEIVED: "default",
  PROCESSED: "success",
  DISCARDED: "muted",
};

export function StatusBadge({ status }: { status: string }) {
  const variant = STATUS_VARIANT[status] ?? "muted";
  return <Badge variant={variant}>{status}</Badge>;
}
