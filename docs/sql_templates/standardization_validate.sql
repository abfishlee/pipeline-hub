-- 표준화 검증 — std_code 매핑 진행률.
-- stg.price_observation 의 std_code 가 NULL/UNMAPPED 인 비율을 source_id 별로 본다.
SELECT
  source_id,
  COUNT(*)                                            AS total_rows,
  COUNT(*) FILTER (WHERE std_code IS NULL)            AS unmapped_rows,
  ROUND(
    COUNT(*) FILTER (WHERE std_code IS NULL)::numeric * 100 / NULLIF(COUNT(*), 0),
    2
  )                                                   AS unmapped_pct
FROM stg.price_observation
WHERE observed_at >= now() - interval '1 day'
GROUP BY source_id
ORDER BY unmapped_pct DESC, total_rows DESC
LIMIT 100
