import { useMemo } from "react";
import { useCatalogTables } from "@/api/v2/mappings";

interface Props {
  value: string;
  onChange: (v: string) => void;
  allowEmpty?: boolean;
  schemaFilter?: string[] | null;
  excludeSchemas?: string[];
}

const ALLOWED_PREFIXES = ["mart", "stg", "wf", "service_mart"];
const DEFAULT_EXCLUDED_SCHEMAS = ["agri_mart", "agri_stg"];

export function CatalogTableSelect({
  value,
  onChange,
  allowEmpty = false,
  schemaFilter,
  excludeSchemas = DEFAULT_EXCLUDED_SCHEMAS,
}: Props) {
  const q = useCatalogTables();

  const grouped = useMemo(() => {
    if (!q.data) return [];
    const tables = q.data.filter((t) => {
      if (excludeSchemas.includes(t.schema_name)) return false;
      if (schemaFilter) return schemaFilter.includes(t.schema_name);
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
  }, [q.data, schemaFilter, excludeSchemas]);

  return (
    <select
      className="mt-1 h-9 w-72 rounded-md border bg-background px-2 text-sm"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={q.isLoading}
    >
      {allowEmpty && <option value="">All tables</option>}
      {!allowEmpty && <option value="">Select table</option>}
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
