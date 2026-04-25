-- 신선도 (source 별) — source_id 별 마지막 수집 시각 + 24h 이내 row 수.
-- 매일 cron 으로 모니터링하면 끊어진 source (last_seen 이 너무 오래됨) 을 빠르게 감지.
SELECT
  source_id,
  MAX(observed_at)                                                  AS last_observed_at,
  EXTRACT(epoch FROM now() - MAX(observed_at)) / 3600.0             AS hours_since_last,
  COUNT(*) FILTER (WHERE observed_at >= now() - interval '24 hour') AS rows_last_24h,
  COUNT(*)                                                          AS rows_total_30d
FROM mart.price_fact
WHERE observed_at >= now() - interval '30 day'
GROUP BY source_id
ORDER BY hours_since_last DESC
LIMIT 100
