-- 결측 비율 — stg.price_observation 의 주요 컬럼별 NULL 비율.
-- DQ_CHECK null_pct_max 임계 결정용 (예: std_code NULL 30% → 임계 40% 로 설정).
SELECT
  COUNT(*) AS total_rows,
  ROUND(COUNT(*) FILTER (WHERE std_code IS NULL)::numeric * 100 / NULLIF(COUNT(*), 0), 2)
    AS null_pct_std_code,
  ROUND(COUNT(*) FILTER (WHERE retailer_code IS NULL)::numeric * 100 / NULLIF(COUNT(*), 0), 2)
    AS null_pct_retailer_code,
  ROUND(COUNT(*) FILTER (WHERE store_name IS NULL)::numeric * 100 / NULLIF(COUNT(*), 0), 2)
    AS null_pct_store_name,
  ROUND(COUNT(*) FILTER (WHERE weight_g IS NULL)::numeric * 100 / NULLIF(COUNT(*), 0), 2)
    AS null_pct_weight_g,
  ROUND(COUNT(*) FILTER (WHERE sale_unit IS NULL)::numeric * 100 / NULLIF(COUNT(*), 0), 2)
    AS null_pct_sale_unit
FROM stg.price_observation
WHERE observed_at >= now() - interval '1 day'
