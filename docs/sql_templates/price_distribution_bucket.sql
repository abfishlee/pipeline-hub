-- 가격 분포 — width_bucket 으로 mart.price_fact 가격을 10개 구간에 분배.
-- 각 구간의 row 수 + median 가격 (오버뷰 차트용).
WITH range AS (
  SELECT
    MIN(price_krw) AS min_price,
    MAX(price_krw) AS max_price
  FROM mart.price_fact
  WHERE observed_at >= now() - interval '1 day'
)
SELECT
  width_bucket(p.price_krw, r.min_price, r.max_price + 1, 10) AS bucket_no,
  COUNT(*)                                                    AS row_count,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p.price_krw)    AS median_price,
  MIN(p.price_krw)                                            AS bucket_min,
  MAX(p.price_krw)                                            AS bucket_max
FROM mart.price_fact p
CROSS JOIN range r
WHERE p.observed_at >= now() - interval '1 day'
GROUP BY width_bucket(p.price_krw, r.min_price, r.max_price + 1, 10)
ORDER BY bucket_no
