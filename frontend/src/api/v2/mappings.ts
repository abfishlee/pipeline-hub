// Phase 6 Wave 2A — Field Mapping Designer client.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../client";

export type MappingStatus = "DRAFT" | "REVIEW" | "APPROVED" | "PUBLISHED";

export interface FieldMapping {
  mapping_id: number;
  contract_id: number;
  source_path: string;
  target_table: string;
  target_column: string;
  transform_expr: string | null;
  data_type: string | null;
  is_required: boolean;
  order_no: number;
  status: MappingStatus;
  created_at: string;
  updated_at: string;
}

export interface FieldMappingIn {
  contract_id: number;
  source_path: string;
  target_table: string;
  target_column: string;
  transform_expr?: string | null;
  data_type?: string | null;
  is_required?: boolean;
  order_no?: number;
}

export interface FunctionSpec {
  name: string;
  category: string;
  description: string;
  arity_min: number;
  arity_max: number | null;
}

export interface TableColumn {
  column_name: string;
  data_type: string;
  is_nullable: boolean;
  ordinal_position: number;
}

export interface ContractLight {
  contract_id: number;
  domain_code: string;
  resource_code: string;
  schema_version: number;
  status: string;
  label: string;
}

const BASE = "/v2/mappings";

export interface ListMappingsParams {
  contract_id?: number;
  target_table?: string;
  status?: MappingStatus;
}

export function useMappings(params: ListMappingsParams = {}) {
  return useQuery({
    queryKey: ["v2-mappings", params],
    queryFn: () =>
      apiRequest<FieldMapping[]>(BASE, { params: { ...params } }),
  });
}

export function useCreateMapping() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: FieldMappingIn) =>
      apiRequest<FieldMapping>(BASE, { method: "POST", body: req }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-mappings"] }),
  });
}

export function useUpdateMapping(mappingId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: FieldMappingIn) =>
      apiRequest<FieldMapping>(`${BASE}/${mappingId}`, {
        method: "PATCH",
        body: req,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-mappings"] }),
  });
}

export function useDeleteMapping() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (mappingId: number) =>
      apiRequest<void>(`${BASE}/${mappingId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-mappings"] }),
  });
}

export function useTransitionMapping(mappingId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (target_status: MappingStatus) =>
      apiRequest<FieldMapping>(`${BASE}/${mappingId}/transition`, {
        method: "POST",
        body: { target_status },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-mappings"] }),
  });
}

export function useFunctionRegistry() {
  return useQuery({
    queryKey: ["v2-functions"],
    staleTime: 5 * 60 * 1000,
    queryFn: () =>
      apiRequest<FunctionSpec[]>(`${BASE}/functions/list`),
  });
}

export function useTableColumns(schemaTable: string | null) {
  return useQuery({
    queryKey: ["v2-table-columns", schemaTable],
    enabled: !!schemaTable && schemaTable.includes("."),
    queryFn: () => {
      if (!schemaTable) throw new Error("schemaTable required");
      const [s, t] = schemaTable.split(".", 2);
      return apiRequest<TableColumn[]>(`${BASE}/columns/${s}/${t}`);
    },
  });
}

// Phase 8.6 — 카탈로그 (SQL Studio + Quality Workbench dropdown 용)
export interface CatalogTable {
  schema_name: string;
  table_name: string;
  table_type: string;
  estimated_rows: number | null;
}

export function useCatalogTables(schema?: string) {
  return useQuery({
    queryKey: ["v2-catalog-tables", schema ?? null],
    staleTime: 60_000,
    queryFn: () =>
      apiRequest<CatalogTable[]>(`${BASE}/catalog/tables`, {
        params: schema ? { schema } : undefined,
      }),
  });
}

export function useContractsLight(domainCode?: string) {
  return useQuery({
    queryKey: ["v2-contracts-light", domainCode ?? null],
    queryFn: () =>
      apiRequest<ContractLight[]>(`${BASE}/contracts/list-light`, {
        params: { domain_code: domainCode },
      }),
  });
}

// dryrun
export interface DryRunFieldMappingRequest {
  domain_code: string;
  contract_id: number;
  source_table: string;
  target_table?: string;
  apply_only_published?: boolean;
}

export interface DryRunSummary {
  dry_run_id: number | null;
  kind: string;
  domain_code: string | null;
  rows_affected: number[];
  row_counts: number[];
  errors: string[];
  duration_ms: number;
  target_summary: Record<string, unknown>;
}

export function useDryRunFieldMapping() {
  return useMutation({
    mutationFn: (req: DryRunFieldMappingRequest) =>
      apiRequest<DryRunSummary>("/v2/dryrun/field-mapping", {
        method: "POST",
        body: req,
      }),
  });
}
