-- mart-stg 정합성 — stg.price_observation 과 mart.price_fact 의 가격 일치 여부.
-- 같은 (source_id, raw_object_id, observed_at) 키로 양쪽을 조회해 price_krw 가 다른 row 수.
WITH joined AS (
  SELECT
    s.source_id,
    s.raw_object_id,
    s.observed_at,
    s.price_krw                              AS stg_price,
    m.price_krw                              AS mart_price
  FROM stg.price_observation s
  JOIN mart.price_fact m
    ON  m.source_id      = s.source_id
    AND m.raw_object_id  = s.raw_object_id
    AND m.observed_at    = s.observed_at
  WHERE s.observed_at >= now() - interval '1 day'
)
SELECT
  COUNT(*)                                              AS joined_rows,
  COUNT(*) FILTER (WHERE stg_price <> mart_price)       AS mismatched_rows,
  ROUND(
    COUNT(*) FILTER (WHERE stg_price <> mart_price)::numeric * 100 / NULLIF(COUNT(*), 0),
    4
  )                                                     AS mismatch_pct
FROM joined
LIMIT 1
