-- 중복 진단 — (source_id, retailer_code, product_name_raw, observed_at) 기준 중복 비율.
-- DEDUP 노드 적용 전후의 row count 변화를 가늠하는 데 사용.
WITH grouped AS (
  SELECT
    source_id,
    retailer_code,
    product_name_raw,
    observed_at,
    COUNT(*) AS dup_n
  FROM stg.price_observation
  WHERE observed_at >= now() - interval '1 day'
  GROUP BY source_id, retailer_code, product_name_raw, observed_at
)
SELECT
  COUNT(*)                                       AS unique_keys,
  SUM(dup_n)                                     AS total_rows,
  SUM(dup_n) - COUNT(*)                          AS removable_dup_rows,
  ROUND(
    (SUM(dup_n) - COUNT(*))::numeric * 100 / NULLIF(SUM(dup_n), 0),
    2
  )                                              AS dup_pct
FROM grouped
LIMIT 1
