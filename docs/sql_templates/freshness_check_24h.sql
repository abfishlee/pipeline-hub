-- 신선도 (전체) — mart.price_fact 의 24h 이내 수집 row 수 + 가장 최근 시각.
-- DAG 실행 후 mart 적재가 정상인지 1줄로 확인하는 핵심 쿼리.
SELECT
  COUNT(*)                                                          AS rows_total,
  COUNT(*) FILTER (WHERE observed_at >= now() - interval '24 hour') AS rows_last_24h,
  COUNT(DISTINCT product_id) FILTER (
    WHERE observed_at >= now() - interval '24 hour'
  )                                                                 AS distinct_products_last_24h,
  MAX(observed_at)                                                  AS most_recent_observed_at
FROM mart.price_fact
WHERE observed_at >= now() - interval '7 day'
LIMIT 1
