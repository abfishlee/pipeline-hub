-- 고아 row 진단 — source_id 이상 또는 미래 날짜 captured_at.
-- ctl.data_source 와 JOIN 은 sqlglot 정책상 차단되므로 stg-only 휴리스틱:
--   1. source_id IS NULL → 절대 발생해서는 안 됨 (NOT NULL 컬럼이지만 INSERT 누락 의심).
--   2. observed_at > now() → 시계 / 입력 불량.
--   3. observed_at < '2020-01-01' → 미지원 옛날 데이터.
SELECT
  COUNT(*) FILTER (WHERE source_id IS NULL)                            AS null_source_id,
  COUNT(*) FILTER (WHERE observed_at > now() + interval '1 hour')      AS future_observed_at,
  COUNT(*) FILTER (WHERE observed_at < TIMESTAMP '2020-01-01')         AS too_old_observed_at,
  COUNT(*)                                                             AS total_rows
FROM stg.price_observation
WHERE observed_at >= now() - interval '7 day'
   OR observed_at IS NULL
LIMIT 1
