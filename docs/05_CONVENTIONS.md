# 05. 개발 컨벤션

## 5.1 언어/이름 규칙

| 대상 | 언어 | 규칙 |
|---|---|---|
| 코드 식별자 (변수/함수/클래스) | 영어 | Python snake_case, TS camelCase, 클래스 PascalCase |
| DB 테이블/컬럼 | 영어 snake_case | 예: `price_fact`, `std_code` |
| 주석 | 한국어 (또는 영어 혼용 허용) | 왜? 를 중심으로 |
| 문서 | 한국어 | docs/ 전체 |
| UI 문자열 | 한국어 | i18n은 Phase 4까지 미도입 |
| 로그 메시지 | 영어 key + 한국어 message 허용 | JSON 로그는 영어 key만 |
| 커밋 메시지 | 한국어 또는 영어 (Conventional Commits 형식) | |

## 5.2 파이썬 스타일

- **포맷/린트**: `ruff format` + `ruff check` (한 도구로 통합).
- **타입힌트**: public 함수는 100% 필수. private(_prefix) 는 권장.
- **max line length**: 100.
- **import 순서**: stdlib → third-party → local. `ruff`가 자동 정리.
- **docstring**: public 함수/클래스는 한 줄 이상. Google style.
- **f-string** 우선. `.format()` 금지. `%` 금지.
- **예외 처리**: `except Exception:` 광범위 포착 금지. 필요 시 명시적 타입 + 로그 + re-raise.
- **print 금지** — `structlog.get_logger()` 사용.
- **pathlib** 사용. `os.path.join` 금지.
- **datetime**: 모든 시간은 UTC + `timezone.aware`. `datetime.now()` 금지 → `datetime.now(tz=timezone.utc)` 또는 `app.core.time.utcnow()`.

## 5.3 TypeScript/React 스타일

- **포맷**: biome 또는 prettier + eslint. 팀이 선호하는 하나로 고정.
- **strict mode** ON. `any` 금지 (예외: 명시적 `unknown` 사용 후 type guard).
- **함수 컴포넌트 only**. 클래스 컴포넌트 금지.
- **훅 순서**: state → derived → effects → handlers → render.
- **prop 명명**: `onXxx` 이벤트 핸들러, `isXxx/hasXxx` 불린.
- **컴포넌트 파일명**: PascalCase (`PipelineDesigner.tsx`).
- **유틸 파일명**: camelCase (`formatPrice.ts`).
- **경로 별칭**: `@/` = `src/`.
- **서버 상태는 TanStack Query에만**. 클라이언트 상태는 Zustand. useState는 로컬 UI 상태 한정.

## 5.4 API 설계

- **버전**: `/v1/...` 프리픽스. 메이저 변경은 `/v2/`.
- **경로**: 복수형 명사. `/v1/sources`, `/v1/pipeline-runs/{id}`.
- **HTTP 메서드**: GET(조회), POST(생성/커맨드), PATCH(부분 수정), PUT(전체 교체, 지양), DELETE(삭제).
- **페이지네이션**: cursor 기반 기본, offset/limit은 관리 화면에만.
- **에러 포맷**:
  ```json
  {
    "error": {
      "code": "INVALID_SOURCE_CODE",
      "message": "source_code 'FOO'가 존재하지 않습니다",
      "request_id": "req-abc123",
      "details": {...}
    }
  }
  ```
- **상관관계 ID**: 모든 요청에 `X-Request-ID` 생성/전파. 로그/에러에 포함.
- **idempotency**: 수집 API는 `Idempotency-Key` 헤더 지원 필수.

## 5.5 DB 사용 규칙

- **스키마 변경**: Alembic migration 필수. 직접 DDL 금지.
- **트랜잭션 경계**: API handler → domain 함수 입구에서 열고 닫기. repository 안에서 commit 금지.
- **N+1 방지**: `selectinload` / `joinedload` 적극 사용. raw SQL 시 EXPLAIN 확인.
- **마스터 테이블 직접 UPDATE 금지**: mart 수정은 SQL Studio 승인 플로우만.
- **LIMIT 없는 SELECT 금지**: 사용자 화면 쿼리는 반드시 `LIMIT`.
- **FOR UPDATE SKIP LOCKED**: outbox/작업큐 조회 시 필수.
- **시계열 파티션 테이블은 항상 partition_date 조건** 포함 쿼리.
- **JSONB 필터**: `@>` 연산자 + `jsonb_path_ops` GIN 인덱스 활용.

## 5.6 설정/비밀

- 모든 설정은 `app/config.py` 의 Pydantic Settings를 통해서만.
- 환경변수 이름: `APP_*` 프리픽스 (예: `APP_DATABASE_URL`, `APP_OBJECT_STORAGE_ENDPOINT`).
- **금지**: 코드에 하드코딩된 URL/키/토큰/password.
- `.env.example` 항상 최신화 (실제 값 없이, 더미값만).
- 운영 비밀은 NCP Secret Manager.

## 5.7 Git / 브랜치 / 커밋

### 5.7.1 브랜치

- `main` — 항상 배포 가능.
- `feature/<짧은-설명>` — 단일 기능 개발.
- `fix/<짧은-설명>` — 버그.
- `chore/<...>` — 의존성, 문서, 빌드.

### 5.7.2 커밋 메시지 (Conventional Commits)

```
<type>(<scope>): <한 줄 요약>

<본문 — 왜 바꿨는지. 무엇을 바꿨는지는 diff가 말한다>
```

**type**: `feat / fix / refactor / test / docs / chore / perf / style / build / ci`
**scope** 예: `ingest, ocr, crawler, sql-studio, db, ui, infra`.

예:
```
feat(ingest): 영수증 업로드 API 추가

CLOVA OCR 연동 전 raw 보존 경로만 먼저 구현.
idempotency_key 헤더 필수화.
```

### 5.7.3 PR 규칙

- 최소 한 개 PR = 한 가지 변경.
- PR 설명: 왜 / 어떻게 / 테스트 방법 / 스크린샷(UI인 경우).
- 머지 전 체크리스트:
  - [ ] 문서 갱신 여부 (스키마 바뀌었으면 `docs/03_DATA_MODEL.md`)
  - [ ] 테스트 추가/갱신
  - [ ] `ruff check`, `mypy`, `pytest` 통과
  - [ ] 프론트 변경 시 브라우저로 확인
  - [ ] 비밀 커밋 안 됨 확인

## 5.8 테스트

### 5.8.1 범위

- **유닛 테스트**: domain/ 함수, core/ 유틸.
- **통합 테스트**: repositories/ → 실제 PG, integrations/ → VCR or httpx_mock.
- **API 테스트**: FastAPI TestClient, DB는 testcontainers-postgres 또는 pytest-postgresql.
- **워커 테스트**: Dramatiq `StubBroker` 사용.
- **E2E (Phase 3+)**: Playwright, 핵심 화면만.

### 5.8.2 최소 기준

- 새 domain 함수 = 최소 **happy path 1 + edge 1** (빈 입력/오류 입력).
- 버그 픽스 = 회귀 테스트 필수.
- 커버리지 목표: 핵심 domain/ 80%+, 전체 60%+.

### 5.8.3 테스트 데이터

- `tests/fixtures/` 에 재사용 가능한 factory.
- 실제 API 호출은 VCR 카세트로 녹화(한 번) / 재생(반복).
- 시드 데이터는 `scripts/seed_*.py` 로 분리.

## 5.9 로깅

- `structlog` + JSON 포맷.
- 필수 필드: `event`, `level`, `request_id`, `user_id`, `duration_ms`(해당 시).
- 도메인 이벤트 로그는 event_type 명확히: `ingest.received`, `ocr.completed` 등.
- **금지**: PII 로깅, 전체 요청 body 로깅 (raw 테이블이 있으므로 불필요).

## 5.10 에러 / 예외

- 도메인 예외는 `app/core/errors.py` 에 정의:
  ```python
  class DomainError(Exception): ...
  class NotFoundError(DomainError): ...
  class ConflictError(DomainError): ...
  class ValidationError(DomainError): ...
  class IntegrationError(DomainError): ...
  ```
- API 층에서 `exception_handler` 로 변환.
- 예상치 못한 500은 `request_id` 와 함께 Sentry (Phase 2+) 로 전송.

## 5.11 성능 기준

- **수집 API p95**: 200ms 이내 (raw 저장은 async 이후).
- **조회 API p95**: 300ms 이내.
- **DB 쿼리**: 화면 쿼리 50ms 이내 목표.
- **N+1 발견 시 즉시 수정**.
- 성능 측정은 Phase 2에서 Prometheus 메트릭으로 자동화.

## 5.12 보안 체크리스트

- [ ] 외부 입력은 Pydantic으로 validation.
- [ ] SQL 쿼리는 SQLAlchemy bind param 또는 text + bindparam. f-string SQL 금지.
- [ ] CORS는 화이트리스트만.
- [ ] JWT secret ≥ 32 bytes.
- [ ] 운영 DB 유저는 최소 권한 (app 유저는 DDL 권한 없음; migration 전용 유저 분리).
- [ ] 로그/에러 메시지에 secret 포함 안 됨.

## 5.13 DRY vs 성급한 추상화

- **3번 반복되면 추상화**. 2번 이하는 중복 허용.
- 도메인 경계 넘는 재사용은 `app/core/` 로만.
- util 폴더 남발 금지.

## 5.14 문서화

- 새 엔드포인트 = FastAPI 자동 OpenAPI.
- 복잡한 알고리즘 (표준화 매칭 등) = `docs/adr/` 또는 `docs/04_DOMAIN_MODEL.md` 에 설명 추가.
- README는 유지보수 의무 없음 (docs/ 가 SoT).

## 5.15 배포 전 체크

- [ ] Alembic migration 로컬 up/down 모두 성공
- [ ] `.env.example` 갱신
- [ ] NCP 배포 스크립트 dry-run
- [ ] 관제 대시보드에 새 메트릭 추가 (필요 시)
- [ ] 롤백 절차 한 문장 명시
