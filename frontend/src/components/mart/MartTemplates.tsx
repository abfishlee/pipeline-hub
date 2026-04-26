// Phase 8.2 — Mart 템플릿 4종.
//
// 처음 사용자가 "어디서부터 시작해야 하지?" 라는 진입장벽 ↓
// 템플릿 클릭 → 폼 자동 채움.
import { Activity, Box, Package, Tags } from "lucide-react";
import type { MartColumnSpec, MartIndexSpec } from "@/api/v2/mart_drafts";

export interface MartTemplate {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
  example_target: string; // schema.table sample (사용자가 도메인에 맞게 변경)
  columns: MartColumnSpec[];
  primary_key: string[];
  partition_key: string | null;
  indexes: MartIndexSpec[];
  recommended_load_mode: "append_only" | "upsert" | "scd_type_2" | "current_snapshot";
}

export const MART_TEMPLATES: MartTemplate[] = [
  {
    key: "price_fact",
    label: "가격 Fact",
    icon: Activity,
    description: "유통사 가격 fact — 일별/시간별 가격 적재 (upsert)",
    example_target: "{domain}_mart.product_price",
    columns: [
      { name: "ymd", type: "TEXT", nullable: false, description: "수집일 YYYYMMDD" },
      { name: "retailer_code", type: "TEXT", nullable: false, description: "유통사 코드" },
      { name: "retailer_product_code", type: "TEXT", nullable: false, description: "유통사 상품코드" },
      { name: "product_name", type: "TEXT", nullable: false, description: "상품명" },
      { name: "price_normal", type: "NUMERIC", nullable: true, description: "정상가" },
      { name: "price_promo", type: "NUMERIC", nullable: true, description: "행사가" },
      { name: "stock_qty", type: "INTEGER", nullable: true, description: "재고 수량" },
      { name: "collected_at", type: "TIMESTAMPTZ", nullable: false, description: "수집 시각" },
      { name: "raw_response", type: "JSONB", nullable: true, description: "원본 응답" },
    ],
    primary_key: ["ymd", "retailer_code", "retailer_product_code"],
    partition_key: "ymd",
    indexes: [
      { name: "idx_price_retailer_ymd", columns: ["retailer_code", "ymd"], unique: false },
    ],
    recommended_load_mode: "upsert",
  },
  {
    key: "product_master",
    label: "상품 Master",
    icon: Package,
    description: "표준 상품 마스터 — 상품명/카테고리/표준코드 (upsert)",
    example_target: "{domain}_mart.product_master",
    columns: [
      { name: "product_code", type: "TEXT", nullable: false, description: "표준 상품코드" },
      { name: "product_name", type: "TEXT", nullable: false, description: "표준 상품명" },
      { name: "category", type: "TEXT", nullable: true, description: "카테고리" },
      { name: "std_code", type: "TEXT", nullable: true, description: "표준코드 (GS1 등)" },
      { name: "brand", type: "TEXT", nullable: true, description: "브랜드" },
      { name: "unit_kind", type: "TEXT", nullable: true, description: "단위 종류 (kg/g/단/봉)" },
      { name: "registered_at", type: "TIMESTAMPTZ", nullable: false, description: "등록 시각" },
      { name: "updated_at", type: "TIMESTAMPTZ", nullable: false, description: "최종 갱신" },
    ],
    primary_key: ["product_code"],
    partition_key: null,
    indexes: [
      { name: "idx_master_category", columns: ["category"], unique: false },
      { name: "idx_master_std_code", columns: ["std_code"], unique: false },
    ],
    recommended_load_mode: "upsert",
  },
  {
    key: "stock_snapshot",
    label: "재고 Snapshot",
    icon: Box,
    description: "매장별 재고 snapshot — 시간별 적재 (append-only)",
    example_target: "{domain}_mart.stock_snapshot",
    columns: [
      { name: "snapshot_at", type: "TIMESTAMPTZ", nullable: false, description: "스냅샷 시각" },
      { name: "store_code", type: "TEXT", nullable: false, description: "매장 코드" },
      { name: "product_code", type: "TEXT", nullable: false, description: "상품코드" },
      { name: "stock_qty", type: "INTEGER", nullable: false, description: "재고 수량" },
      { name: "stock_status", type: "TEXT", nullable: true, description: "IN_STOCK / OUT_OF_STOCK / LOW_STOCK" },
      { name: "expected_restock", type: "DATE", nullable: true, description: "입고 예정일" },
      { name: "last_check_at", type: "TIMESTAMPTZ", nullable: true, description: "마지막 확인 시각" },
    ],
    primary_key: ["snapshot_at", "store_code", "product_code"],
    partition_key: "snapshot_at",
    indexes: [
      { name: "idx_stock_store", columns: ["store_code", "snapshot_at"], unique: false },
    ],
    recommended_load_mode: "append_only",
  },
  {
    key: "promo_fact",
    label: "행사 Fact",
    icon: Tags,
    description: "할인/행사 정보 — 시작일/종료일 + 할인율 (upsert)",
    example_target: "{domain}_mart.promo_fact",
    columns: [
      { name: "promo_id", type: "TEXT", nullable: false, description: "행사 ID" },
      { name: "retailer_code", type: "TEXT", nullable: false, description: "유통사 코드" },
      { name: "product_code", type: "TEXT", nullable: false, description: "상품코드" },
      { name: "promo_type", type: "TEXT", nullable: false, description: "CARD_DISCOUNT / ONE_PLUS_ONE / PERIOD_DISCOUNT" },
      { name: "promo_start", type: "TIMESTAMPTZ", nullable: false, description: "행사 시작" },
      { name: "promo_end", type: "TIMESTAMPTZ", nullable: false, description: "행사 종료" },
      { name: "discount_rate", type: "NUMERIC", nullable: true, description: "할인율 (0.10 = 10%)" },
      { name: "promo_price", type: "NUMERIC", nullable: true, description: "행사가" },
      { name: "registered_at", type: "TIMESTAMPTZ", nullable: false, description: "등록 시각" },
    ],
    primary_key: ["promo_id"],
    partition_key: null,
    indexes: [
      { name: "idx_promo_retailer", columns: ["retailer_code", "promo_start"], unique: false },
      { name: "idx_promo_active", columns: ["promo_end", "promo_start"], unique: false },
    ],
    recommended_load_mode: "upsert",
  },
];

interface MartTemplatesProps {
  onSelect: (template: MartTemplate) => void;
}

export function MartTemplates({ onSelect }: MartTemplatesProps) {
  return (
    <div className="space-y-2">
      <div className="text-xs font-semibold uppercase text-muted-foreground">
        템플릿으로 시작 (선택)
      </div>
      <div className="grid grid-cols-2 gap-2">
        {MART_TEMPLATES.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => onSelect(t)}
              className="flex flex-col gap-1 rounded-md border border-border bg-background p-2 text-left text-xs transition hover:border-primary hover:bg-primary/5"
            >
              <div className="flex items-center gap-1 font-semibold">
                <Icon className="h-3.5 w-3.5 text-primary" />
                {t.label}
              </div>
              <div className="text-[10px] text-muted-foreground">
                {t.description}
              </div>
              <code className="text-[9px] text-muted-foreground">
                {t.example_target}
              </code>
            </button>
          );
        })}
      </div>
      <p className="text-[10px] text-muted-foreground">
        ※ 템플릿 선택 후 도메인/컬럼 추가 수정 가능. 빈 폼 으로 시작하려면 템플릿
        선택 없이 직접 입력.
      </p>
    </div>
  );
}
