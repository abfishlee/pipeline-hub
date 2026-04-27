// Phase 8.6 — Cron Picker (사용자 친화적 6 모드).
//
// 운영자가 cron 5필드를 직접 입력하지 않고 모드별 dropdown 으로 작성.
// 다음 실행 시각 미리보기까지 포함.
//
// 모드:
//   - manual    : 수동 실행 only (cron 빈 문자열)
//   - every_n_min   : N 분마다 (1/5/10/15/30)
//   - every_n_hour  : N 시간마다 (1/2/3/6/12)
//   - daily_at      : 매일 HH:MM
//   - weekly_at     : 특정 요일들 + HH:MM
//   - advanced      : cron 5필드 직접 입력 (파워유저)

import { Clock } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Input } from "@/components/ui/input";

type Mode =
  | "manual"
  | "every_n_min"
  | "every_n_hour"
  | "daily_at"
  | "weekly_at"
  | "advanced";

interface CronPickerProps {
  /** 현재 cron 식 (UTC, 5필드) — 빈 문자열 = manual */
  value: string;
  onChange: (cron: string) => void;
  /** 활성 토글 (schedule_enabled). cron 비면 자동 disabled */
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
}

const MIN_OPTIONS = [1, 5, 10, 15, 30];
const HOUR_OPTIONS = [1, 2, 3, 6, 12];
const WEEKDAYS = [
  { v: 1, l: "월" },
  { v: 2, l: "화" },
  { v: 3, l: "수" },
  { v: 4, l: "목" },
  { v: 5, l: "금" },
  { v: 6, l: "토" },
  { v: 0, l: "일" },
];

/** cron 5필드 → 모드/파라미터 reverse-engineer */
function detectMode(cron: string): {
  mode: Mode;
  param?: number | string;
  hh?: number;
  mm?: number;
  weekdays?: number[];
} {
  const c = cron.trim();
  if (!c) return { mode: "manual" };
  const parts = c.split(/\s+/);
  if (parts.length !== 5) return { mode: "advanced" };
  const [m, h, dom, mon, dow] = parts;
  // every_n_min: */N * * * *
  if (m.startsWith("*/") && h === "*" && dom === "*" && mon === "*" && dow === "*") {
    return { mode: "every_n_min", param: Number(m.slice(2)) };
  }
  // every_n_hour: 0 */N * * *
  if (m === "0" && h.startsWith("*/") && dom === "*" && mon === "*" && dow === "*") {
    return { mode: "every_n_hour", param: Number(h.slice(2)) };
  }
  // daily_at: MM HH * * *
  if (
    /^\d+$/.test(m) &&
    /^\d+$/.test(h) &&
    dom === "*" &&
    mon === "*" &&
    dow === "*"
  ) {
    return { mode: "daily_at", hh: Number(h), mm: Number(m) };
  }
  // weekly_at: MM HH * * 1,3,5
  if (
    /^\d+$/.test(m) &&
    /^\d+$/.test(h) &&
    dom === "*" &&
    mon === "*" &&
    /^[\d,]+$/.test(dow)
  ) {
    return {
      mode: "weekly_at",
      hh: Number(h),
      mm: Number(m),
      weekdays: dow.split(",").map(Number),
    };
  }
  return { mode: "advanced" };
}

function buildCron(state: {
  mode: Mode;
  nMin: number;
  nHour: number;
  hh: number;
  mm: number;
  weekdays: number[];
  advanced: string;
}): string {
  const { mode, nMin, nHour, hh, mm, weekdays, advanced } = state;
  switch (mode) {
    case "manual":
      return "";
    case "every_n_min":
      return `*/${nMin} * * * *`;
    case "every_n_hour":
      return `0 */${nHour} * * *`;
    case "daily_at":
      return `${mm} ${hh} * * *`;
    case "weekly_at":
      if (weekdays.length === 0) return `${mm} ${hh} * * *`;
      return `${mm} ${hh} * * ${[...weekdays].sort().join(",")}`;
    case "advanced":
      return advanced;
  }
}

/** UTC cron 의 다음 실행 시각 N개 — 간단한 시뮬레이션. 모든 분을 평가. */
function nextExecutions(cron: string, count = 3): Date[] {
  if (!cron.trim()) return [];
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return [];
  const [mField, hField, , , dowField] = parts;

  // simple matcher
  const matchField = (val: number, expr: string): boolean => {
    if (expr === "*") return true;
    if (expr.startsWith("*/")) {
      const n = Number(expr.slice(2));
      return n > 0 && val % n === 0;
    }
    if (expr.includes(",")) {
      return expr.split(",").map(Number).includes(val);
    }
    return Number(expr) === val;
  };

  const out: Date[] = [];
  const now = new Date();
  // 시작 = 다음 분
  let cur = new Date(
    Math.ceil((now.getTime() + 1) / 60_000) * 60_000,
  );
  for (let i = 0; i < 60 * 24 * 14 && out.length < count; i++) {
    const m = cur.getUTCMinutes();
    const h = cur.getUTCHours();
    const dow = cur.getUTCDay();
    if (matchField(m, mField) && matchField(h, hField) && matchField(dow, dowField)) {
      out.push(new Date(cur));
    }
    cur = new Date(cur.getTime() + 60_000);
  }
  return out;
}

export function CronPicker({
  value,
  onChange,
  enabled,
  onEnabledChange,
}: CronPickerProps) {
  const detected = useMemo(() => detectMode(value), [value]);
  const [mode, setMode] = useState<Mode>(detected.mode);
  const [nMin, setNMin] = useState<number>(
    detected.mode === "every_n_min" ? Number(detected.param) || 5 : 5,
  );
  const [nHour, setNHour] = useState<number>(
    detected.mode === "every_n_hour" ? Number(detected.param) || 1 : 1,
  );
  const [hh, setHh] = useState<number>(detected.hh ?? 5);
  const [mm, setMm] = useState<number>(detected.mm ?? 0);
  const [weekdays, setWeekdays] = useState<number[]>(detected.weekdays ?? [1, 3, 5]);
  const [advanced, setAdvanced] = useState<string>(
    detected.mode === "advanced" ? value : "0 5 * * *",
  );

  // 모드 / 파라미터 변경 시 cron 재계산 + onChange.
  useEffect(() => {
    const newCron = buildCron({
      mode,
      nMin,
      nHour,
      hh,
      mm,
      weekdays,
      advanced,
    });
    if (newCron !== value) onChange(newCron);
    // cron 비면 enabled 강제 off
    if (!newCron && enabled) onEnabledChange(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, nMin, nHour, hh, mm, weekdays, advanced]);

  const upcoming = useMemo(() => nextExecutions(value, 3), [value]);

  return (
    <div className="space-y-2 rounded-md border border-border bg-card p-3 text-sm">
      <div className="flex items-center gap-2">
        <Clock className="h-3.5 w-3.5 text-primary" />
        <span className="font-semibold">실행 주기</span>
        <span className="text-[10px] text-muted-foreground">UTC 기준</span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={mode}
          onChange={(e) => setMode(e.target.value as Mode)}
        >
          <option value="manual">수동 실행만 (스케줄 없음)</option>
          <option value="every_n_min">N 분마다</option>
          <option value="every_n_hour">N 시간마다</option>
          <option value="daily_at">매일 특정 시각</option>
          <option value="weekly_at">특정 요일 + 시각</option>
          <option value="advanced">고급 — cron 5필드</option>
        </select>

        {mode === "every_n_min" && (
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={nMin}
            onChange={(e) => setNMin(Number(e.target.value))}
          >
            {MIN_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} 분
              </option>
            ))}
          </select>
        )}

        {mode === "every_n_hour" && (
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={nHour}
            onChange={(e) => setNHour(Number(e.target.value))}
          >
            {HOUR_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n} 시간
              </option>
            ))}
          </select>
        )}

        {(mode === "daily_at" || mode === "weekly_at") && (
          <>
            <Input
              type="number"
              min={0}
              max={23}
              className="h-9 w-16 text-sm"
              value={hh}
              onChange={(e) => setHh(Number(e.target.value) || 0)}
            />
            <span>시</span>
            <Input
              type="number"
              min={0}
              max={59}
              className="h-9 w-16 text-sm"
              value={mm}
              onChange={(e) => setMm(Number(e.target.value) || 0)}
            />
            <span>분 (UTC)</span>
          </>
        )}

        {mode === "advanced" && (
          <Input
            value={advanced}
            onChange={(e) => setAdvanced(e.target.value)}
            placeholder="0 5 * * *"
            className="h-9 w-40 font-mono text-xs"
          />
        )}
      </div>

      {mode === "weekly_at" && (
        <div className="flex flex-wrap items-center gap-1 text-xs">
          <span className="text-muted-foreground">요일:</span>
          {WEEKDAYS.map((w) => (
            <button
              key={w.v}
              type="button"
              onClick={() =>
                setWeekdays((cur) =>
                  cur.includes(w.v)
                    ? cur.filter((x) => x !== w.v)
                    : [...cur, w.v],
                )
              }
              className={`rounded-md border px-2 py-0.5 ${
                weekdays.includes(w.v)
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border"
              }`}
            >
              {w.l}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 text-xs">
        <label className="flex items-center gap-1">
          <input
            type="checkbox"
            checked={enabled && value.trim().length > 0}
            disabled={!value.trim()}
            onChange={(e) => onEnabledChange(e.target.checked)}
          />
          <span>활성</span>
        </label>
        <span className="text-muted-foreground">
          cron: <code className="font-mono">{value || "(수동 실행)"}</code>
        </span>
      </div>

      {upcoming.length > 0 && (
        <div className="rounded-md bg-muted/40 p-2 text-[11px]">
          <span className="font-semibold text-muted-foreground">다음 실행 (UTC):</span>
          <ul className="ml-2 mt-0.5 space-y-0.5">
            {upcoming.map((d, i) => (
              <li key={i} className="font-mono">
                {d.toISOString().replace("T", " ").slice(0, 16)}{" "}
                <span className="text-muted-foreground">
                  ({d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })} KST)
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
