-- 매장 × 품목 카디널리티 — 매장 (seller_id) 별 고유 product_id 수.
-- 라인업이 갑자기 줄거나 늘면 수집 누락 / 매장 폐점 의심.
SELECT
  seller_id,
  COUNT(DISTINCT product_id)                                  AS distinct_products,
  COUNT(*)                                                    AS total_observations,
  MIN(observed_at)                                            AS first_seen,
  MAX(observed_at)                                            AS last_seen
FROM mart.price_fact
WHERE observed_at >= now() - interval '7 day'
GROUP BY seller_id
ORDER BY distinct_products DESC
LIMIT 100
