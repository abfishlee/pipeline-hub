// Phase 8.2 — DQ rule 추천 세트.
//
// "어떤 품질 규칙을 걸어야 하는지 모르는" 사용자에게 시작점 제공.
import { AlertTriangle, Calendar, GitMerge, Wand2 } from "lucide-react";
import type { DqRuleKind, DqSeverity } from "@/api/v2/dq_rules";

export interface DqRuleTemplate {
  key: string;
  label: string;
  rule_kind: DqRuleKind;
  rule_json: Record<string, unknown>;
  severity: DqSeverity;
  description: string;
}

export interface DqTemplateCategory {
  key: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  templates: DqRuleTemplate[];
}

export const DQ_TEMPLATE_CATEGORIES: DqTemplateCategory[] = [
  {
    key: "required",
    label: "필수값 검증",
    icon: AlertTriangle,
    templates: [
      {
        key: "price_not_null",
        label: "가격 NULL 차단",
        rule_kind: "null_pct_max",
        rule_json: { column: "price", max_pct: 0 },
        severity: "ERROR",
        description: "price 컬럼에 NULL 이 하나라도 있으면 실패",
      },
      {
        key: "product_code_not_null",
        label: "상품코드 NULL 차단",
        rule_kind: "null_pct_max",
        rule_json: { column: "product_code", max_pct: 0 },
        severity: "ERROR",
        description: "product_code NULL 차단",
      },
      {
        key: "row_count_min_1",
        label: "최소 1행 이상",
        rule_kind: "row_count_min",
        rule_json: { min: 1 },
        severity: "ERROR",
        description: "수집된 데이터가 0행이면 실패",
      },
      {
        key: "row_count_min_100",
        label: "최소 100행 이상",
        rule_kind: "row_count_min",
        rule_json: { min: 100 },
        severity: "WARN",
        description: "정상 운영 시 일별 최소 100행 (이하 시 경고)",
      },
    ],
  },
  {
    key: "outlier",
    label: "이상값 검증",
    icon: AlertTriangle,
    templates: [
      {
        key: "price_positive",
        label: "가격 0원 또는 음수 차단",
        rule_kind: "range",
        rule_json: { column: "price", min: 1, max: 100000000 },
        severity: "ERROR",
        description: "가격은 1원 이상 1억원 이하",
      },
      {
        key: "stock_non_negative",
        label: "재고 음수 차단",
        rule_kind: "range",
        rule_json: { column: "stock_qty", min: 0, max: 100000 },
        severity: "ERROR",
        description: "재고는 0 이상 10만 이하",
      },
      {
        key: "discount_rate_valid",
        label: "할인율 0~100% 범위",
        rule_kind: "range",
        rule_json: { column: "discount_rate", min: 0.0, max: 1.0 },
        severity: "ERROR",
        description: "할인율은 0.0 ~ 1.0",
      },
      {
        key: "price_anomaly_zscore",
        label: "가격 이상치 (Z-score)",
        rule_kind: "anomaly_zscore",
        rule_json: { column: "price", threshold: 3.0 },
        severity: "WARN",
        description: "평균±3σ 벗어나면 경고",
      },
    ],
  },
  {
    key: "temporal",
    label: "기간 검증",
    icon: Calendar,
    templates: [
      {
        key: "promo_period_valid",
        label: "행사 종료일 ≥ 시작일",
        rule_kind: "custom_sql",
        rule_json: {
          sql: "SELECT COUNT(*) FROM {target_table} WHERE promo_end < promo_start",
        },
        severity: "ERROR",
        description: "행사 종료일이 시작일보다 빠른 row 차단",
      },
      {
        key: "no_future_dates",
        label: "수집일 미래 날짜 차단",
        rule_kind: "custom_sql",
        rule_json: {
          sql: "SELECT COUNT(*) FROM {target_table} WHERE collected_at > NOW()",
        },
        severity: "ERROR",
        description: "수집일이 미래 timestamp 인 row 차단",
      },
      {
        key: "freshness_24h",
        label: "24시간 내 데이터 존재",
        rule_kind: "freshness",
        rule_json: { max_age_minutes: 1440 },
        severity: "WARN",
        description: "최신 row 가 24시간 이상 안 들어오면 경고",
      },
    ],
  },
  {
    key: "uniqueness",
    label: "중복/일관성 검증",
    icon: GitMerge,
    templates: [
      {
        key: "unique_product_code",
        label: "상품코드 + 매장 unique",
        rule_kind: "unique_columns",
        rule_json: { columns: ["store_code", "product_code"] },
        severity: "ERROR",
        description: "같은 매장-상품 조합 중복 차단",
      },
      {
        key: "unique_price_snapshot",
        label: "수집일+상품 unique",
        rule_kind: "unique_columns",
        rule_json: { columns: ["ymd", "retailer_product_code"] },
        severity: "ERROR",
        description: "같은 날짜+상품 중복 적재 차단",
      },
      {
        key: "fk_product_master",
        label: "상품코드 → master 참조",
        rule_kind: "reference",
        rule_json: {
          column: "product_code",
          ref: "service_mart.std_product.std_product_code",
        },
        severity: "WARN",
        description: "표준 상품 마스터에 없는 product_code 경고",
      },
    ],
  },
];

interface DqRuleTemplatesProps {
  targetTable: string;
  onSelect: (template: DqRuleTemplate) => void;
}

export function DqRuleTemplates({ targetTable, onSelect }: DqRuleTemplatesProps) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase text-muted-foreground">
        <Wand2 className="h-3.5 w-3.5" />
        추천 템플릿 (선택)
      </div>
      {DQ_TEMPLATE_CATEGORIES.map((cat) => {
        const Icon = cat.icon;
        return (
          <div key={cat.key} className="space-y-1">
            <div className="flex items-center gap-1 text-[11px] font-semibold text-foreground">
              <Icon className="h-3 w-3" />
              {cat.label}
            </div>
            <div className="grid grid-cols-2 gap-1 md:grid-cols-4">
              {cat.templates.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() =>
                    onSelect({
                      ...t,
                      rule_json: substituteTargetTable(t.rule_json, targetTable),
                    })
                  }
                  className="flex flex-col gap-0.5 rounded-md border border-border bg-background p-2 text-left text-[10px] transition hover:border-primary hover:bg-primary/5"
                  title={t.description}
                >
                  <span className="font-semibold">{t.label}</span>
                  <span className="text-muted-foreground">
                    {t.rule_kind} · {t.severity}
                  </span>
                </button>
              ))}
            </div>
          </div>
        );
      })}
      <p className="text-[10px] text-muted-foreground">
        ※ 클릭 시 폼이 자동 채워짐. 저장 전 도메인/대상 테이블/임계값 수정 가능.
      </p>
    </div>
  );
}

function substituteTargetTable(
  rj: Record<string, unknown>,
  targetTable: string,
): Record<string, unknown> {
  const out = { ...rj };
  if (typeof out.sql === "string") {
    out.sql = (out.sql as string).replace(/\{target_table\}/g, targetTable);
  }
  return out;
}
