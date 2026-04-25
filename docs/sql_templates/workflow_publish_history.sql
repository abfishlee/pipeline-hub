-- 배포 이력 — 최근 30일간 wf.pipeline_release 의 workflow 별 마지막 version_no.
-- 운영 회의에서 "이번 분기 무엇이 PUBLISHED 되었나" 한눈에 보기.
SELECT
  workflow_name,
  MAX(version_no)        AS latest_version,
  COUNT(*)               AS release_count_30d,
  MAX(released_at)       AS last_released_at,
  MIN(released_at)       AS first_released_at
FROM wf.pipeline_release
WHERE released_at >= now() - interval '30 day'
GROUP BY workflow_name
ORDER BY last_released_at DESC
LIMIT 100
