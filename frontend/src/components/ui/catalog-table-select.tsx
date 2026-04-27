// Phase 8.6 — 카탈로그 기반 테이블 dropdown.
//
// SQL Studio / Quality Workbench / Mart 등 *기존 mart 테이블* 을 선택해야 하는 화면에서
// 자유 텍스트 입력 대신 dropdown 으로 사용. 카테고리별 그룹핑 (mart / stg / wf / 기타).
import { useMemo } from "react";
import { useCatalogTables } from "@/api/v2/mappings";

interface Props {
  value: string;
  onChange: (v: string) => void;
  allowEmpty?: boolean;
  /** 어떤 schema 만 노출할지 (예: ['mart','agri_mart']). null/undefined = 전체 */
  schemaFilter?: string[] | null;
}

const ALLOWED_PREFIXES = ["mart", "stg", "wf", "service_mart"];

export function CatalogTableSelect({
  value,
  onChange,
  allowEmpty = false,
  schemaFilter,
}: Props) {
  const q = useCatalogTables();

  const grouped = useMemo(() => {
    if (!q.data) return [];
    const tables = q.data.filter((t) => {
      if (schemaFilter) return schemaFilter.includes(t.schema_name);
      // 기본: *_mart, *_stg, mart, service_mart, stg, wf 만
      return (
        t.schema_name.endsWith("_mart") ||
        t.schema_name.endsWith("_stg") ||
        ALLOWED_PREFIXES.includes(t.schema_name)
      );
    });
    const buckets = new Map<string, typeof tables>();
    for (const t of tables) {
      const key = t.schema_name;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(t);
    }
    return Array.from(buckets.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [q.data, schemaFilter]);

  return (
    <select
      className="mt-1 h-9 w-72 rounded-md border bg-background px-2 text-sm"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={q.isLoading}
    >
      {allowEmpty && <option value="">— 전체 —</option>}
      {!allowEmpty && <option value="">— 선택 —</option>}
      {grouped.map(([schema, tables]) => (
        <optgroup key={schema} label={schema}>
          {tables.map((t) => {
            const fqdn = `${t.schema_name}.${t.table_name}`;
            return (
              <option key={fqdn} value={fqdn}>
                {t.table_name}
                {t.estimated_rows != null
                  ? ` (~${t.estimated_rows.toLocaleString()} rows)`
                  : ""}
              </option>
            );
          })}
        </optgroup>
      ))}
    </select>
  );
}
