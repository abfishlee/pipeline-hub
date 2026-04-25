-- 이상치 (MAD) — 표준코드별 MAD 기준 가격 이상치.
-- median ± 5 * MAD 를 벗어나는 가격을 표시. MAD = median(|x - median(x)|).
WITH stats AS (
  SELECT
    p.product_id,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY p.price_krw) AS med,
    PERCENTILE_CONT(0.5) WITHIN GROUP (
      ORDER BY ABS(p.price_krw - PERCENTILE_CONT(0.5)
        WITHIN GROUP (ORDER BY p.price_krw) OVER (PARTITION BY p.product_id))
    ) AS mad
  FROM mart.price_fact p
  WHERE p.observed_at >= now() - interval '7 day'
  GROUP BY p.product_id
)
SELECT
  s.product_id,
  s.med           AS median_price,
  s.mad           AS mad_price,
  s.med - 5 * s.mad AS lower_5mad,
  s.med + 5 * s.mad AS upper_5mad
FROM stats s
WHERE s.mad > 0
ORDER BY s.mad DESC
LIMIT 100
