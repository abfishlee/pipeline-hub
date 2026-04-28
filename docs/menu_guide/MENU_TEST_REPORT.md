# 메뉴별 자동 테스트 결과

**최종 갱신:** 2026-04-28
**테스트 도구:** Playwright + headless Chromium
**테스트 환경:** backend `http://127.0.0.1:8000` + frontend `http://127.0.0.1:5173`
**계정:** admin / admin

## 실행 명령

```bash
cd frontend
node scripts/test_all_menus.mjs
```

스크립트는 각 메뉴 페이지를 navigate 한 뒤 다음을 수집:
- console.error
- pageerror (uncaught exception)
- HTTP 4xx/5xx 응답
- 네트워크 실패 (`requestfailed`)

SSE long-poll URL (`/events`) 과 Vite HMR 은 무시 처리.

## 결과 — 26/26 통과 ✓

| 카테고리 | # | 메뉴 | URL | 결과 |
|---|---|---|---|---|
| 진입 | 1 | Dashboard | `/` | ✓ |
| Build | 2 | Source / API Connector | `/v2/connectors/public-api` | ✓ |
| Build | 3 | Inbound Channel | `/v2/inbound-channels/designer` | ✓ |
| Build | 4 | Mart Workbench | `/v2/marts/designer` | ✓ |
| Build | 5 | Field Mapping Designer | `/v2/mappings/designer` | ✓ |
| Build | 6 | Transform Designer | `/v2/transforms/designer` | ✓ |
| Build | 7 | Quality Workbench | `/v2/quality/designer` | ✓ |
| Build | 8 | ETL Canvas V2 (new) | `/v2/pipelines/designer` | ✓ |
| Build | 9 | ETL Canvas V2 (existing #2) | `/v2/pipelines/designer/2` | ✓ |
| Run | 10 | Pipeline Runs | `/pipelines/runs` | ✓ |
| Run | 11 | Pipeline Run Detail | `/pipelines/runs/2` | ✓ |
| Run | 12 | Releases | `/pipelines/releases` | ✓ |
| Operate | 13 | Service Mart Viewer | `/v2/service-mart` | ✓ |
| Operate | 14 | Raw Objects | `/raw-objects` | ✓ |
| Operate | 15 | Collection Jobs | `/jobs` | ✓ |
| Operate | 16 | Master Merge | `/master-merge` | ✓ |
| Operate | 17 | SQL Studio | `/sql-studio` | ✓ |
| Operate | 18 | Review Queue | `/crowd-tasks` | ✓ |
| Operate | 19 | Operations Dashboard | `/v2/operations/dashboard` | ✓ |
| Operate | 20 | Runtime Monitor | `/runtime` | ✓ |
| Admin | 21 | Mock API (테스트) | `/v2/mock-api` | ✓ |
| Admin | 22 | Dead Letters | `/dead-letters` | ✓ |
| Admin | 23 | Users | `/users` | ✓ |
| Admin | 24 | API Keys | `/api-keys` | ✓ |
| Admin | 25 | Security Events | `/security-events` | ✓ |
| Admin | 26 | Partition Archive | `/admin/partitions` | ✓ |

## 검증 중 발견 + 수정한 이슈

| # | 메뉴 | 증상 | 원인 | 수정 |
|---|---|---|---|---|
| 1 | Quality Workbench | `/v2/mappings/catalog/tables` 500 (Internal Server Error) | `_do(s)` 가 Session 인자 받는데 `asyncio.to_thread(_do)` 가 인자 없이 호출 (`_run_in_sync` wrapper 누락) | `_run_in_sync` wrapper 추가 |
| 2 | Quality Workbench | React duplicate key 경고 — `(schema, table)` 같은 row 가 2건 (emart_mart.product_price, service_mart.product_price) | catalog SQL 의 LEFT JOIN 이 schema 매칭 없이 `pg_class.relname = table_name` 만 비교하여 동명 테이블이 다른 schema 의 pg_class 와 cross join | JOIN 조건에 `c.relnamespace = n.oid` 추가 + JOIN 순서 정정 |
| 3 | Pipeline Run Detail | navigate timeout (`waitUntil: networkidle` 도달 못 함) | `/v1/pipelines/runs/{id}/events` SSE long-poll 로 인해 networkidle 영구 미도달 | 테스트 스크립트의 `waitUntil` 을 `load` 로 완화 + `/events` URL 패턴 ignore |

## JSON 상세 결과

`docs/menu_guide/test_results.json` — 각 메뉴의 `consoleErrors` / `failedResponses` / `networkErrors` / `finalUrl` 등 상세 기록.

## 재실행 방법

```bash
# 1. backend 가동 확인
curl http://127.0.0.1:8000/healthz

# 2. frontend dev 가동 확인
curl http://127.0.0.1:5173/

# 3. 테스트 실행
cd frontend
node scripts/test_all_menus.mjs
```

스크립트는 idempotent — 데이터 변경 없이 *읽기 전용* navigate 만.
