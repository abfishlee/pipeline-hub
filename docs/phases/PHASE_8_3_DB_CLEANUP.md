# Phase 8.3 — DB 정리 마이그레이션 (운영 이관 전 cleanup)

**날짜:** 2026-04-27
**선행 검증:** dp_postgres 컨테이너 실측 (사용자 분석 26항목 + Claude 재검증)
**목적:** Phase 4 운영팀 합류 전, 미사용/구버전/spike 흔적을 제거하여 운영 DB 단순화

---

## 0. 검증 결과 (2026-04-27 dp_postgres 실측)

| 카테고리 | 정리 후보 | DB 실측 | 결정 |
|---|---|---|---|
| **즉시 정리 (안전)** | `iot_spike_mart.*` (4 테이블) | spike 잔재 1~3 rows, 코드 참조 없음 | ✅ DROP SCHEMA CASCADE |
| | `ctl.connector` | 0 rows, ORM 모델만 정의됨 (import 없음) | ✅ DROP TABLE |
| | `ctl.api_key.expired_at` | 3 rows 모두 null, 코드 read/write 없음 | ✅ DROP COLUMN |
| **미래 기능 (보류)** | `raw.db_snapshot`, `raw.db_cdc_event`, `ctl.cdc_subscription` | 0 rows | ⏸ CDC 활성 시 사용 — 유지 |
| | `crowd.payout`, `crowd.skill_tag` | 0 rows | ⏸ Crowd 정식 운영 시 사용 — 유지 |
| | `mart.price_daily_agg` | 0 rows | ⏸ 일별 집계 배치 구현 결정 후 — 유지 |
| | `agri_mart.kamis_price` | 0 rows | ⏸ Phase 9 KAMIS 실증 — 유지 |
| | `audit.provider_usage_*` | 2 partition 모두 0 | ⏸ Provider Registry — 유지 |
| **별도 작업 (Phase 8.3 외)** | `mart.standard_code.embedding` IVFFLAT | 6 rows에 1.6 MB | 🔄 Phase 9 표준코드 1k+ rows 시점에 재생성 — 별도 PR |
| | 파티션 정책 rolling | 9 partition 중 8개 빈 채 | 🔄 자동 생성 cron — 별도 PR |
| | matview 추가 (`pipeline_run_daily_summary`, `current_price`) | 현재 0개 | 🔄 운영 대시보드 부하 측정 후 — 별도 PR |
| | autovacuum threshold 하향 | dead tuple 비율 높음 | 🔄 운영 이관 시 — `infra/`에 별도 작업 |

---

## 1. Migration 0052 변경 사항

### 1.1 `iot_spike_mart` schema 제거
- 0030_spike_iot.py 의 `downgrade()` 와 동일 효과: `DROP SCHEMA IF EXISTS iot_spike_mart CASCADE`
- spike 코드(`backend/app/experimental/`, `tests/integration/test_registry_spike.py`)는
  유지하되 **테스트는 `pytest.mark.skip`** — 향후 ADR-0017 spike PoC 흔적 보존

### 1.2 `ctl.connector` 테이블 제거
- ORM 모델만 정의되고 import 없음 (코드 의존성 0건)
- v2 generic 플랫폼은 `domain.public_api_connector` / `domain.sql_asset` 등으로 대체됨
- FK: `ctl.connector.source_id → ctl.data_source.source_id` — drop 시 FK 자동 제거

### 1.3 `ctl.api_key.expired_at` 컬럼 제거
- migration 0026 호환 기간 종료 (Phase 7+ 신규 코드는 `expires_at` 사용)
- 코드 read/write 없음, 0% 사용률
- ORM 모델에서도 제거 → `expires_at` 단일화

### 1.4 ORM 모델 정리
- `backend/app/models/ctl.py`:
  - `class Connector` 삭제
  - `DataSource.connectors` relationship 삭제
  - `ApiKey.expired_at` 삭제

### 1.5 Spike 테스트 skip 마킹
- `backend/tests/integration/test_registry_spike.py` 에 `pytestmark = pytest.mark.skip(reason="Phase 8.3: iot_spike_mart schema removed")`
- 코드 자체는 ADR-0017 의 근거 자료로 보존

---

## 2. Downgrade 정책

운영 DB 손실 가능 영역이므로 **downgrade 시 데이터는 복구 불가**. 빈 테이블/컬럼만 재생성:

```python
def downgrade():
    # 0030 의 upgrade 와 동일 (4 spike 테이블)
    # ctl.connector 재생성 (빈 테이블)
    # ctl.api_key.expired_at 재추가 (NULL)
```

운영 환경에서는 downgrade 가 사실상 의미 없음 — forward-only 정책.

---

## 3. 테스트 영향

| 테스트 | 영향 |
|---|---|
| `tests/integration/test_registry_spike.py` | **Skip** (Phase 8.3 마킹) |
| `tests/integration/test_phase6_public_api.py` | 영향 없음 (ApiKey.expires_at 사용) |
| `tests/integration/test_phase8_*` | 영향 없음 |
| 14 + spike — 1 = **13 active integration tests** |

---

## 4. 실행 절차

```bash
# 1) 마이그레이션 적용
cd backend && alembic upgrade head

# 2) 검증 (직접 SQL)
docker exec dp_postgres psql -U app -d datapipeline -c "
  SELECT to_regclass('ctl.connector') AS connector,        -- NULL 기대
         to_regnamespace('iot_spike_mart') AS spike_schema, -- NULL 기대
         column_name FROM information_schema.columns
         WHERE table_schema='ctl' AND table_name='api_key' AND column_name='expired_at';
"

# 3) 테스트
pytest tests/ -x

# 4) 프런트엔드 빌드 (영향 없지만 회귀 확인)
pnpm --prefix frontend build
```

---

## 5. Phase 8.3 산출물

- `migrations/versions/0052_phase8_3_db_cleanup.py` (신규)
- `backend/app/models/ctl.py` (수정)
- `backend/tests/integration/test_registry_spike.py` (skip 마킹)
- 본 문서

---

## 6. 다음 (Phase 9 이전 별도 PR)

- pgvector IVFFLAT 재정책 (표준코드 1k+ rows 도달 시점)
- 파티션 자동 생성 cron + rolling 정책
- matview 2종 (`audit.pipeline_run_daily_summary`, `service_mart.current_price`)
- autovacuum threshold 운영 튜닝
