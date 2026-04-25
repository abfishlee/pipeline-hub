-- 이상 변동 — 어제 vs 오늘 가격 변동률 ±10% 초과 product_id top 50.
-- 가격 폭등/폭락을 빠르게 감지. PERCENTILE 평균 사용으로 단발 이상치 영향 완화.
WITH today_avg AS (
  SELECT
    product_id,
    AVG(price_krw) AS avg_today
  FROM mart.price_fact
  WHERE observed_at >= CURRENT_DATE
  GROUP BY product_id
),
yesterday_avg AS (
  SELECT
    product_id,
    AVG(price_krw) AS avg_yesterday
  FROM mart.price_fact
  WHERE observed_at >= CURRENT_DATE - interval '1 day'
    AND observed_at <  CURRENT_DATE
  GROUP BY product_id
)
SELECT
  t.product_id,
  y.avg_yesterday,
  t.avg_today,
  ROUND((t.avg_today - y.avg_yesterday) * 100 / NULLIF(y.avg_yesterday, 0), 2) AS pct_change
FROM today_avg t
JOIN yesterday_avg y USING (product_id)
WHERE y.avg_yesterday > 0
  AND ABS((t.avg_today - y.avg_yesterday) / y.avg_yesterday) > 0.10
ORDER BY ABS((t.avg_today - y.avg_yesterday) / y.avg_yesterday) DESC
LIMIT 50
