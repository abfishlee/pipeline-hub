import { useState } from "react";
import { type JobStatus, type JobType, useJobs } from "@/api/jobs";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/ui/table";
import { formatDateTime, formatNumber } from "@/lib/format";

const STATUSES: JobStatus[] = [
  "PENDING",
  "RUNNING",
  "SUCCESS",
  "FAILED",
  "CANCELLED",
];
const JOB_TYPES: JobType[] = ["ON_DEMAND", "SCHEDULED", "RETRY", "BACKFILL"];

export function JobsPage() {
  const [sourceIdInput, setSourceIdInput] = useState("");
  const [status, setStatus] = useState<JobStatus | "">("");
  const [jobType, setJobType] = useState<JobType | "">("");
  const [page, setPage] = useState(0);
  const limit = 20;

  const sourceId = sourceIdInput.trim()
    ? Number(sourceIdInput.trim())
    : undefined;

  const jobs = useJobs({
    source_id: Number.isFinite(sourceId) ? sourceId : undefined,
    status: status || undefined,
    job_type: jobType || undefined,
    limit,
    offset: page * limit,
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <Filter label="source_id">
            <Input
              type="number"
              min={1}
              className="w-32"
              value={sourceIdInput}
              onChange={(e) => {
                setSourceIdInput(e.target.value);
                setPage(0);
              }}
            />
          </Filter>
          <Filter label="status">
            <select
              className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value as JobStatus | "");
                setPage(0);
              }}
            >
              <option value="">(전체)</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Filter>
          <Filter label="job_type">
            <select
              className="flex h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={jobType}
              onChange={(e) => {
                setJobType(e.target.value as JobType | "");
                setPage(0);
              }}
            >
              <option value="">(전체)</option>
              {JOB_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Filter>
          <div className="ml-auto flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              이전
            </Button>
            <span className="text-sm text-muted-foreground">
              page {page + 1}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={(jobs.data?.length ?? 0) < limit}
              onClick={() => setPage((p) => p + 1)}
            >
              다음
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {jobs.isLoading && <div className="p-4 text-sm">불러오는 중...</div>}
          {jobs.data && jobs.data.length === 0 && (
            <div className="p-4 text-sm text-muted-foreground">결과 없음</div>
          )}
          {jobs.data && jobs.data.length > 0 && (
            <Table>
              <Thead>
                <Tr>
                  <Th>job_id</Th>
                  <Th>source_id</Th>
                  <Th>type</Th>
                  <Th>status</Th>
                  <Th>입력</Th>
                  <Th>출력</Th>
                  <Th>오류</Th>
                  <Th>생성</Th>
                  <Th>완료</Th>
                </Tr>
              </Thead>
              <Tbody>
                {jobs.data.map((j) => (
                  <Tr key={j.job_id}>
                    <Td className="font-mono">{j.job_id}</Td>
                    <Td className="font-mono">{j.source_id}</Td>
                    <Td>{j.job_type}</Td>
                    <Td>
                      <StatusBadge status={j.status} />
                    </Td>
                    <Td className="font-mono">{formatNumber(j.input_count)}</Td>
                    <Td className="font-mono">{formatNumber(j.output_count)}</Td>
                    <Td className="font-mono text-destructive">
                      {formatNumber(j.error_count)}
                    </Td>
                    <Td className="text-xs">{formatDateTime(j.created_at)}</Td>
                    <Td className="text-xs">{formatDateTime(j.finished_at)}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Filter({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      {children}
    </div>
  );
}
