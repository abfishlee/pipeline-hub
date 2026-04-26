# Phase 7 — 공용 데이터 수집 플랫폼 완성

> 목적: Phase 6 까지 만든 *6 workbench + ETL Canvas + Dry-run + Publish* 위에
> 글로벌 데이터 엔지니어링 표준 패턴을 적용하여 **"농축수산물 가격 사업"
> 외에도 재사용 가능한 공용 데이터 수집 플랫폼**을 완성한다.
>
> 도메인 특화 작업 (예: 유통사 4개 API 등록, 행사가/재고 SCD2 모델링 등)
> 은 본 Phase 의 *공용 기능* 이 완성된 후 별도 *Phase 8 실증* 으로 진행한다.

작성일: 2026-04-26
선행 Phase: Phase 6 commit `754135d` (Wave 7 + ADR-0021 회고 완료)

---

## 0. 한 문장

> **"기능은 다 있는데 60~70% 만 공용화" → "100% 공용 + 글로벌 표준 정렬"**

Phase 6 까지: 6 workbench / ETL Canvas v2 / KAMIS 13분 시연 = *제품 골격* 완성.
Phase 7 이후: 같은 시스템으로 **API / Push / Upload / DB / CDC / Provider Result**
모두 동일 공통 구조로 수용 + 자산 버전 pinning + 통합 모니터링.

---

## 1. 진단 — Phase 6 종료 시점의 공용 기능 매트릭스

### 1.1 공용 기능 적용 현황 (사용자 분석 + Claude 분석 합본)

| 공용 기능 | 적용도 | 현재 구현 | 부족한 부분 |
|---|:---:|---|---|
| Source / API Connector 등록 | 🟢 95% | `domain.public_api_connector` + `/v2/connectors/public-api` + 테스트 호출 | — |
| 다양한 수집 채널 수용 | 🟡 50% | API/OCR/Crawler/DB 노드 dispatcher 등록 | **push / upload / event 패턴 부재** |
| Source Contract / Data Contract | 🟡 70% | `domain.source_contract` + compatibility check | semver / breaking change detect 부재 |
| Field Mapping | 🟢 90% | source_path → target_column + 26+ 함수 + dry-run | — |
| Transform 공통화 | 🟡 65% | SQL/HTTP/Function/OCR/Crawl 노드 14종 | **upstream sample 자동 전달 부재** + LLM 응답 표준 패턴 부재 |
| DQ Rule Builder | 🟡 75% | 6종 rule + custom_sql preview | freshness / anomaly / drift rule 부재 |
| Standardization | 🟡 60% | namespace + alias_only / embedding_3stage | external_api 전략 + alias CRUD UI 부재 |
| Mart Designer | 🟢 85% | mart_design_draft + DDL diff | breaking ALTER 거부 + migration 자동 적용 부재 |
| Load Policy | 🟡 60% | append_only / upsert ✅, **scd_type_2 / current_snapshot 미구현** | SCD2 노드 backing 필요 |
| Canvas Builder | 🟢 90% | v2 13종 palette + 자산 dropdown drawer | partial replay (특정 노드만 재실행) 부재 |
| Dry-run / Sandbox | 🟡 55% | 노드별 dry-run + workflow DAG dry-run | **노드 간 임시 결과 자동 전달** + expected vs actual diff 부재 |
| Publish / Approval | 🟡 70% | Mini Checklist 7항목 + ADMIN 승인 | **자산 version pinning** 강화 필요 |
| Schedule / Trigger | 🟡 55% | cron + Airflow + manual | **이벤트 기반 trigger 부재** |
| Monitoring / Observability | 🟡 55% | run/node_run + SSE + Prometheus | **통합 채널 dashboard 부재** |
| Replay / Backfill | 🟡 50% | backend `/v2/backfill` 있음 | UX 부재. 노드 단위 partial replay 부재 |
| Provider Registry | 🟡 50% | OCR/Crawler/HTTP provider model + binding | **secondary path** 에 머무름. primary 전환 필요 |

### 1.2 GAP 한 줄 요약

> **수집 채널은 "API 받아오기" 에 강하지만, "받기 / 올리기 / 끌어오기" 6 종 중
> 4 종이 부족.** Dry-run 은 *노드 단위* 만 강함. 자산 versioning 은 *모델만 있고
> pinning 은 미흡*. Provider Registry 는 *secondary path*. 통합 모니터링 부재.

### 1.3 사용자가 묘사한 시나리오 § 1 ~ § 11 매핑

(참조: 사용자 작성 *공용 데이터 수집 파이프라인 기반 농축수산물 가격 데이터
플랫폼 구상* 문서)

| 시나리오 | 즉시 가능? | Phase 7 작업 항목 |
|---|---|---|
| 1) 대형 유통사 4개 API 수집 | ✅ | 도메인 특화 — Phase 8 |
| 2) 전처리 로직 설계 | ✅ | 단, 상품 규격 normalizer 추가 — Phase 8 |
| 3) 품목 마스터 마트 설계 | ✅ | — |
| 4) Canvas 조립 + 저장 | ✅ | — |
| 5) Dry-run + 운영 전환 | 🟡 | **Wave 4 (sandbox 강화)** |
| 6) 운영 모니터링 + 재처리 | 🟡 | **Wave 5 (Operations Dashboard)** |
| 7) 8~20개 프로세스 동시 운영 | ✅ | 인프라 검증됨 |
| 8) 크롤링 / OCR push 수신 | ❌ | **Wave 1 (Source generalization)** |
| 8) 소상공인 이벤트 업로드 | ❌ | **Wave 1 + Wave 6 (event trigger)** |
| 8) DB-to-DB | 🟡 | **Wave 1 (DB_INCREMENTAL_FETCH 노드화)** |
| 9) 외부 LLM API 전처리 | 🟡 | **Wave 3 (Provider primary path)** |
| 10) 행사가 / 재고 / 가격 변경 이력 | 🟡 | **Wave 2 (SCD2 + asset version)** + Phase 8 |

---

## 2. 목표 — 공용 플랫폼 완성

### 2.1 비전

```
Phase 6 (제품 골격)                       Phase 7 (공용 표준 완성)
──────────────────────────────           ───────────────────────────────────
6 workbench + Canvas + dry-run     →     + 7 source 노드 일반화 (PULL/PUSH/UPLOAD/DB/CDC)
KAMIS 1건 시연                       →     + 자산 version pinning (8 entity 모두)
"Phase 6 acceptance"                →     + Provider Registry primary path
                                    →     + Sandbox 전체 DAG 임시 결과 전달
                                    →     + Operations Dashboard (channel/node 단위)
                                    →     + Event-driven trigger
                                    →     + Replay 노드 단위 부분 재실행
```

### 2.2 5 + 2 핵심 작업 (사용자 분석)

| # | 작업 | Wave |
|---|---|---|
| 1 | Source 종류 일반화 (PULL/PUSH/UPLOAD/DB/CDC/PROVIDER_RESULT) | Wave 1 |
| 2 | Dry-run 전체 DAG sandbox execution 강화 | Wave 4 |
| 3 | 모든 설계 자산 versioning/pinning 완성 | Wave 2 |
| 4 | Provider Registry 를 OCR/Crawler/AI 의 primary path 로 | Wave 3 |
| 5 | Canvas 자산선택→실행→모니터링→수정→재배포 흐름 완성 | Wave 5 |
| 6 | Event-driven trigger (소상공인 업로드 등) | Wave 6 |
| 7 | Schema evolution + Data Contract semver | Wave 7 |

### 2.3 Phase 7 acceptance — 5가지 시나리오 (사용자 § 15.8 결정)

본 Phase 종료 시점에 다음이 *코드 수정 0* 으로 가능해야 한다.

1. **외부 크롤링 업체 push 수용**
   ```text
   외부 업체 → POST /v1/inbound/{channel_code}
                ↓ HMAC SHA256 검증 (replay window ±5분) + idempotency
                ↓ raw_object 저장
                ↓ outbox event
                ↓ workflow trigger
                ↓ Canvas 의 WEBHOOK_INGEST 노드부터 실행
                ↓ Mart 적재
   ```

2. **소상공인 업로드 즉시 처리**
   ```text
   사용자 업로드 → POST /v1/inbound/{channel_code}/upload (multipart)
                  ↓ object storage 저장
                  ↓ 이벤트 기반 trigger
                  ↓ Canvas 의 FILE_UPLOAD_INGEST 노드 실행
   ```

3. **자산 버전 pinning + 운영 안전성**
   - 운영 중인 workflow 가 사용하는 mapping `v3` 을 누군가 수정 시도 → 사용자 confirm
     → DRAFT `v4` 자동 fork
   - 운영 workflow 는 계속 `v3` pinning. 새 `v4` 는 별도 dry-run 후 PUBLISHED 로 전환 시점에만 swap

4. **노드 단위 재실행**
   - run 결과 화면에서 "이 박스만 다시 실행" 버튼
   - 동일 sandbox 환경에서 partial DAG 만 재실행 후 결과 비교

5. **API Pull 회귀 (Phase 6 보장)** ★ 사용자 § 15.8 보완
   - **Phase 6 의 KAMIS 13분 시나리오가 Phase 7 종료 후에도 동일하게 동작** 보장
   - 매 Wave 종료 시 회귀 테스트로 검증 (`test_phase6_kamis_vertical_slice.py` 통과)
   - PUBLIC_API_FETCH + MAP_FIELDS + DQ_CHECK + LOAD_TARGET 4박스 e2e dry-run 성공
   - 새 7 source 노드 도입 후에도 PUBLIC_API_FETCH 의 dispatcher / config_json /
     자산 dropdown 호환성 유지

---

## 3. 글로벌 표준 매트릭스 (사용자 분석)

본 Phase 는 다음 글로벌 표준 패턴을 모두 수용한다.

| 글로벌 표준 | 우리 시스템 적용 | Wave |
|---|---|---|
| **Data Contract** (Open Data Contract Standard, dbt model contract) | source contract semver + compatibility 자동 검증 | Wave 7 |
| **Bronze / Silver / Gold** (Databricks Medallion) | `<domain>_raw` (Bronze) → `<domain>_stg` (Silver) → `<domain>_mart` (Gold) | 이미 있음 — 명명 표준화 |
| **Idempotent Ingestion** (Snowpipe / Singer / Airbyte) | 모든 inbound endpoint 에 `idempotency_key` 강제 | Wave 1 |
| **Outbox Pattern** (Microservices Patterns by Chris Richardson) | 이미 있음 (Phase 4) — event trigger 와 통합 | Wave 6 |
| **Schema Evolution** (Avro / Protobuf / dbt model contract) | source_contract `schema_version` + breaking change 자동 감지 | Wave 7 |
| **DQ Rule Catalog** (Great Expectations / Soda / dbt tests) | 6종 rule → 11종으로 확장 (freshness / anomaly / drift / referential integrity 추가) | Wave 4 |
| **Provider Registry** (Singer Tap / Airbyte connector / Kafka Connect SMT) | `provider_definition` + binding 을 OCR/Crawler/AI 호출의 primary path 로 | Wave 3 |
| **Sandbox Dry-run** (dbt seed/snapshot/test, Dataform incremental) | DAG 전체 sandbox 실행 + rollback + diff 보고 | Wave 4 |
| **Versioned Assets** (Airflow DAG version, Dagster asset version) | 8 entity 모두 version pinning | Wave 2 |
| **Observability** (OpenTelemetry, Datadog Pipelines, Prefect Cloud) | workflow / node / source / provider 단위 통합 dashboard | Wave 5 |
| **Replay / Backfill** (Airflow Backfill, dbt deferred run) | 노드 단위 partial replay + workflow 단위 backfill UI | Wave 5 |
| **Sensor / Event Trigger** (Airflow Sensor / TriggerDagRunOperator) | webhook + outbox → workflow trigger | Wave 6 |
| **Data Lineage** (OpenLineage, Marquez) | run → input/output table 자동 기록 | Phase 8 backlog |

---

## 4. 7 source 노드 일반화 (Wave 1 핵심)

### 4.1 현재 source 종류 vs 목표

| # | source kind | 현재 노드 | Phase 7 목표 노드 | 상태 |
|---|---|---|---|---|
| 1 | API pull | `PUBLIC_API_FETCH` | 그대로 | ✅ 완성 |
| 2 | 외부 시스템 push (웹훅) | (없음) | **`WEBHOOK_INGEST`** | 🆕 신설 |
| 3 | file upload (사용자) | (없음) | **`FILE_UPLOAD_INGEST`** | 🆕 신설 |
| 4 | OCR result push | `OCR_TRANSFORM` (역할 다름) | **`OCR_RESULT_INGEST`** | 🆕 신설 (기존 OCR_TRANSFORM 은 우리가 OCR 호출하는 별도 패턴) |
| 5 | Crawler result push | `CRAWL_FETCH` (역할 다름) | **`CRAWLER_RESULT_INGEST`** | 🆕 신설 (기존 CRAWL_FETCH 는 우리가 크롤링 실행) |
| 6 | DB incremental | (Canvas 노드 미노출) | **`DB_INCREMENTAL_FETCH`** | 🆕 노드화 (백엔드 `db_incremental.py` 활용) |
| 7 | CDC event | (Canvas 노드 미노출) | **`CDC_EVENT_FETCH`** | 🆕 노드화 (백엔드 `wal2json_consumer.py` 활용) |

### 4.2 공통 ingest envelope

모든 source kind 가 다음 공통 구조로 raw_object 에 저장된다 (Bronze layer).

```python
# domain.raw_object (또는 새 테이블 audit.inbound_event)
@dataclass
class IngestEnvelope:
    # ─── 공통 메타 ──────────────────────────────────────
    envelope_id: int               # PK
    source_kind: str               # PULL / PUSH / UPLOAD / DB / CDC / PROVIDER_RESULT
    channel_code: str              # 외부 채널 식별 (예: "kamis", "vendor_a_crawler")
    domain_code: str               # 도메인
    received_at: datetime          # 수신 시각
    idempotency_key: str           # 중복 방지 (UNIQUE)
    request_id: str                # 추적 ID

    # ─── 인증 (push/upload 만) ─────────────────────────
    sender_signature: str | None   # HMAC SHA256 (Stripe pattern)
    sender_ip: str | None
    api_key_id: int | None         # 외부 시스템 인증 키

    # ─── payload ──────────────────────────────────────
    content_type: str              # application/json / xml / csv / image/* / ...
    payload_size_bytes: int
    payload_object_key: str        # NCP Object Storage 의 raw 위치
    payload_inline: dict | None    # 작은 JSON 은 인라인 (≤ 8KB)

    # ─── 처리 상태 ────────────────────────────────────
    status: str                    # RECEIVED / PROCESSING / DONE / FAILED / DLQ
    workflow_run_id: int | None    # 어떤 workflow 가 처리했는지
    error_message: str | None
```

### 4.3 7 source 노드 spec 요약

| 노드 | trigger | 인증 | 입력 | 출력 |
|---|---|---|---|---|
| `PUBLIC_API_FETCH` | cron / 수동 | connector spec 의 secret_ref | endpoint URL + params | output_table (sandbox staging) |
| `WEBHOOK_INGEST` | event | HMAC + replay protection | inbound envelope | output_table |
| `FILE_UPLOAD_INGEST` | event | API key + scope | object_key | output_table (CSV/Excel/JSON 자동 파싱) |
| `OCR_RESULT_INGEST` | event | API key + provider_code | OCR JSON 결과 (text + bbox + confidence) | output_table |
| `CRAWLER_RESULT_INGEST` | event | API key + provider_code | crawler JSON 결과 (rows + lineage URL) | output_table |
| `DB_INCREMENTAL_FETCH` | cron / 수동 | DB connection (provider) | watermark column + last_value | output_table (변경분만) |
| `CDC_EVENT_FETCH` | event (slot 구독) | replication slot | wal2json LSN / op / table / row | output_table (insert/update/delete 분기) |

### 4.4 inbound endpoint 표준 (Wave 1)

모든 push/upload 채널이 같은 endpoint 패턴 사용.

```text
POST /v1/inbound/{channel_code}                  # JSON body
POST /v1/inbound/{channel_code}/upload           # multipart
POST /v1/inbound/{channel_code}/ocr-result       # OCR 업체 전용
POST /v1/inbound/{channel_code}/crawler-result   # 크롤러 업체 전용
```

공통 헤더:
- `X-Idempotency-Key` (필수)
- `X-Signature: hmac-sha256=...` (인증)
- `X-Channel-Version` (data contract semver)
- `X-Request-Id` (전파)

응답:
- `202 Accepted` — RECEIVED 상태로 즉시 ACK (async 처리)
- `409 Conflict` — 동일 idempotency_key 이미 처리됨
- `401 Unauthorized` — HMAC 불일치
- `422 Unprocessable Entity` — schema mismatch (Wave 7 의 contract 검증)

---

## 5. 자산 버전 관리 (Wave 2 핵심)

### 5.1 8 entity 모두 version pinning

| 자산 | 현재 status 머신 | Phase 7 추가 |
|---|---|---|
| `public_api_connector` | DRAFT/REVIEW/APPROVED/PUBLISHED | `version` 컬럼 + auto-fork on update |
| `source_contract` | 동일 | semver (major.minor.patch) + compatibility |
| `field_mapping` | 동일 | (mapping_set 단위) version + workflow pinning |
| `dq_rule` | 동일 | version + workflow pinning |
| `sql_asset` | 동일 + version 이미 있음 | workflow pinning |
| `mart_design_draft` | 동일 | (사용자 § 5.2) — version 컬럼 추가 |
| `load_policy` | 동일 + version 이미 있음 | workflow pinning |
| `workflow_definition` | DRAFT/PUBLISHED/ARCHIVED + version 있음 | 자식 자산 version 모두 pinning |

### 5.2 Auto-fork 정책

```python
# 사용자가 PUBLISHED 자산을 수정 시도 → 자동 새 DRAFT version
def update_asset_with_autofork(asset_id, new_data, user_id):
    asset = load(asset_id)
    if asset.status in ("APPROVED", "PUBLISHED"):
        # 새 version 생성 (DRAFT)
        new_version = asset.version + 1
        new_asset = clone(asset, version=new_version, status="DRAFT", **new_data)
        return new_asset    # 사용자에게 "v{new_version} 으로 분기됨" 표시
    else:
        # DRAFT 는 직접 수정
        return update_inplace(asset, **new_data)
```

### 5.3 Workflow 의 자산 pinning

```text
wf.workflow_definition (workflow_id=42, version=1, status=PUBLISHED)
├── node "fetch_kamis"   config_json: {"connector_id": 7, "connector_version": 3}
├── node "map_fields"    config_json: {"mapping_set_id": 12, "mapping_version": 5}
├── node "dq_check"      config_json: {"rule_ids": [3, 4], "rule_versions": [2, 1]}
└── node "load_target"   config_json: {"policy_id": 8, "policy_version": 4}
```

운영 중인 workflow 는 *항상* 특정 version 을 pinning. 자산이 새 version 으로 fork
되어도 operating workflow 는 영향 없음.

### 5.4 Workflow swap = 새 version PUBLISH

```text
[현재 운영]                              [PUBLISH 후]
workflow v3 (mapping v5)        →       workflow v4 (mapping v6)
                                         (DRAFT v4 → REVIEW → APPROVED → PUBLISHED 시점에 swap)
```

`wf.pipeline_release` 에 매번 새 row INSERT — 이전 release 도 보존. 롤백은 이전 release 재활성.

---

## 6. Provider Registry primary path (Wave 3 핵심)

### 6.1 현재 vs 목표

```
[현재 — Wave 3 시작 전]
OCR_TRANSFORM 노드 → 코드 안에 `_call_clova_api()` 직접 함수 호출
HTTP_TRANSFORM 노드 → secret_ref 만 provider, 호출 자체는 노드 안

[목표 — Wave 3 종료 후]
OCR_TRANSFORM 노드
  ↓
provider_factory.get_provider(domain_code, kind="OCR_TRANSFORM")
  ↓
ProviderInstance (clova_v3, upstage_v2, ...) — 동적 로딩
  ↓
공통 정책: timeout / retry / circuit_breaker / cost_log / DLQ
```

### 6.2 Provider 공통 정책 8가지

모든 외부 서비스 (OCR / Crawler / AI / 주소정제 / 코드표준화 등) 가 같은 패턴.

| 정책 | 구현 |
|---|---|
| `secret_ref` | NCP Secret Manager 참조 (이미 있음) |
| `timeout_sec` | provider 별 (default 15s) |
| `retry_max` + `retry_backoff` | exponential backoff (이미 있음) |
| `circuit_breaker` | 5분 내 N회 실패 → OPEN → HALF_OPEN → CLOSED (이미 있음) |
| `fallback_provider_code` | primary 실패 시 secondary 자동 호출 |
| `cost_per_call` | provider table 에 단가 + 호출 1건 = audit row |
| `usage_log` | `audit.provider_usage` (provider, request_count, cost_total) |
| `dlq_topic` | 실패 envelope → DLQ 이동 + ADMIN 알림 |

### 6.3 Provider 종류 확장

| provider_kind | 현재 | Phase 7 |
|---|---|---|
| `OCR` | clova / upstage | + 표준 응답 schema (text + bbox + confidence) |
| `CRAWLER` | 자체 | + 외부 업체 push 패턴 (`CRAWLER_RESULT_INGEST` 노드와 페어) |
| `HTTP_TRANSFORM` | generic | 그대로 |
| `LLM_CLASSIFY` | (없음) | 🆕 OpenAI / Anthropic / Clova HCX (Function Calling + JSON Schema) |
| `ADDRESS_NORMALIZE` | (없음) | 🆕 도로명/지번 표준화 |
| `PRODUCT_CANONICALIZE` | (없음) | 🆕 상품명 정규화 (GS1 GDSN style) |
| `CODE_LOOKUP` | (없음) | 🆕 외부 코드 매핑 (대형마트 ↔ KAMIS code 등) |

---

## 7. Sandbox Dry-run 강화 (Wave 4 핵심)

### 7.1 현재 dry-run 한계

Phase 6 Wave 5 의 `/v2/dryrun/workflow/{id}` 는 *각 노드 독립 dry-run*:
- 노드 1 의 output_table → 노드 2 의 source_table 자동 주입은 됨
- 하지만 *각 노드는 개별 트랜잭션 + rollback*. 노드 간 sandbox table 이 *실제로
  데이터를 가지지 않음* (rollback 직후 사라짐)

### 7.2 Phase 7 sandbox execution

```python
# 새 패턴: workflow 전체를 단일 sandbox session 안에서 실행
@router.post("/v2/dryrun/workflow/{workflow_id}/sandbox")
async def workflow_sandbox(workflow_id: int):
    sandbox_db = create_sandbox_clone()  # mart 만 read-only mirror
    sandbox_run_id = uuid4()
    try:
        for node in topologically_ordered(workflow.nodes):
            output_table = f"sb_{sandbox_run_id}_{node.node_key}"
            ctx = NodeV2Context(session=sandbox_db, ..., dry_run=True)
            output = run_node(ctx, node.config | {"output_table": output_table})
            persist_intermediate(sandbox_db, output_table, output.rows[:1000])
            collect_diff(node, output)  # expected vs actual diff
        load_target_diff = simulate_mart_changes(sandbox_db, mart_table, planned_rows)
        return SandboxResult(
            nodes=[...],
            mart_diff=load_target_diff,  # CREATE / UPDATE / NO-OP rows 추정
            samples_per_node={...},
            duration_ms=...,
        )
    finally:
        drop_sandbox(sandbox_db)  # 정리
```

### 7.3 강화된 dry-run 결과 (Wave 4)

| 정보 | 현재 | 목표 |
|---|---|---|
| 노드별 status | ✅ | ✅ |
| 노드별 row_count | ✅ | ✅ |
| 노드별 sample 5건 | ❌ (payload 만) | 🆕 input/output sample table |
| 다음 노드로 *실제 데이터* 전달 | ❌ (각 노드 독립) | 🆕 sandbox 안에서 실제 row 흐름 |
| Mart impact preview | ❌ | 🆕 INSERT N / UPDATE M / SKIP K rows 추정 |
| Expected vs actual diff | ❌ | 🆕 사용자가 등록한 `expected_schema` 와 비교 |
| DQ failed sample | 🟡 (DQ_CHECK 노드 결과만) | 🆕 통합 보고 |

### 7.4 DQ Rule catalog 확장 (11종)

| 기존 6종 | 추가 5종 (글로벌 표준) |
|---|---|
| row_count_min | `freshness` — 최근 N분 내 데이터 도착 |
| null_pct_max | `anomaly_zscore` — 평균 ± N σ 이탈 |
| unique_columns | `anomaly_iqr` — 사분위 범위 이탈 |
| reference | `drift_kl` — KL divergence 로 분포 변화 감지 |
| range | `referential_integrity` — FK like + cascade |
| custom_sql | |

---

## 8. Operations Dashboard (Wave 5 핵심)

### 8.1 새 페이지 `/v2/operations/dashboard`

```text
┌──────────────────────────────┬───────────────────────────────────────┐
│ Channels (workflow 8~20개)    │ Selected: kamis_daily (workflow #42)  │
│ ─────────────────────────────│ ─────────────────────────────────────│
│ ● kamis_daily         99.7%  │ Run history (last 7d):                │
│ ● vendor_a_api        100%   │ ┌──────────────────────────────────┐ │
│ ● vendor_b_api        95.2%  │ │  fetch  →  map  →  dq  →  load   │ │
│ ● ocr_receipts        87.3%  │ │  ✅      ✅       ⚠       ✅      │ │
│ ● crawler_online      100%   │ │  ✅      ✅       ✅       ✅      │ │
│ ● smb_uploads         (event)│ │  ✅      ✅       ✅       ❌      │ │
│ ─────────────────────────────│ │  ✅      ✅       ✅       ✅      │ │
│ Aggregate                    │ └──────────────────────────────────┘ │
│   24h success: 96.5%         │                                       │
│   24h rows ingested: 287,341 │ Failed run #1234 (load_target):       │
│   pending replay: 3 runs     │   error: connection timeout           │
│   provider failures: 0       │   ▶ retry this node only              │
│                              │   ▶ retry from this node              │
└──────────────────────────────┴───────────────────────────────────────┘
```

### 8.2 노드 단위 partial replay

```python
@router.post("/v1/pipelines/runs/{run_id}/replay-from")
async def replay_from_node(run_id: int, node_key: str):
    """특정 노드부터 끝까지 재실행. upstream 결과는 cache 에서."""
    run = load_run(run_id)
    upstream_outputs = load_upstream_results(run, until_node=node_key)
    new_run = create_replay_run(run, start_from=node_key, prior_outputs=upstream_outputs)
    enqueue_dramatiq(new_run)
    return new_run
```

### 8.3 Source / Provider observability

| 메트릭 | 항목 | 알림 |
|---|---|---|
| source ingestion lag | 마지막 성공 run 으로부터 경과 분 | > schedule_cron 의 2배 시 |
| provider failure rate | 5분 평균 실패율 | > 10% 시 |
| circuit_breaker state | OPEN 진입 | 즉시 ADMIN |
| node error rate per workflow | 24h 평균 | > 5% 시 |
| DQ block count | severity=BLOCK 결과 | 1건이라도 발생 시 |

---

## 9. Event-driven Trigger (Wave 6 핵심)

### 9.1 트리거 종류 확장

```python
# wf.workflow_definition.trigger_kind: 새 컬럼
TRIGGER_KINDS = ["cron", "event", "manual", "external_api"]

# wf.workflow_event_binding (신규 테이블)
class WorkflowEventBinding:
    binding_id: int
    workflow_id: int           # 트리거할 workflow
    event_source: str          # "inbound_event" / "outbox" / "external_webhook"
    event_filter: dict         # {"channel_code": "smb_upload"} 같은 매칭
    is_active: bool
```

### 9.2 흐름

```text
소상공인 업로드: POST /v1/inbound/smb_upload/upload (multipart)
  ↓
audit.inbound_event INSERT (status=RECEIVED)
  ↓
trigger 1: outbox event 발행 (event_type=inbound.received, channel_code=smb_upload)
  ↓
event dispatcher (Dramatiq actor) 가 outbox 구독
  ↓
matching workflow_event_binding 조회 → workflow_id 결정
  ↓
trigger_pipeline_run(workflow_id, run_kind=event, input_envelope_id=...)
  ↓
Canvas 의 FILE_UPLOAD_INGEST 노드부터 실행 (envelope_id 가 input)
  ↓
Mart 적재 → audit.inbound_event status=DONE
```

### 9.3 latency 목표

| 경로 | 목표 | 현재 | 달성 후 |
|---|---|---|---|
| inbound endpoint → 202 ACK | < 200ms | 없음 | < 100ms |
| envelope 수신 → workflow trigger | < 5s | N/A | < 1s |
| workflow trigger → mart 적재 | < 60s (단순 4박스) | 30~120s | < 30s |

---

## 10. Schema Evolution + Data Contract semver (Wave 7 핵심)

### 10.1 source_contract semver

```python
# 현재
class SourceContract:
    schema_version: int  # 1, 2, 3, ...

# 목표
class SourceContract:
    schema_version_major: int  # breaking changes
    schema_version_minor: int  # additive (new optional field)
    schema_version_patch: int  # docs / metadata
    compatibility_mode: str    # "BACKWARD" / "FORWARD" / "FULL" / "NONE"
```

### 10.2 호환성 자동 검증 (`/v2/contracts/check-compatibility` 강화)

```python
def check_breaking_change(old_schema, new_schema) -> list[BreakingChange]:
    """
    BACKWARD compatibility (default for ingestion):
      - field 제거 = breaking
      - field type 변경 = breaking
      - required 추가 = breaking
      - optional 추가 = OK (minor++)
    """
    breaks = []
    for old_field in old_schema.fields:
        if not new_schema.has(old_field.name):
            breaks.append(f"field {old_field.name} removed")
        elif new_schema.field(old_field.name).type != old_field.type:
            breaks.append(f"field {old_field.name} type changed")
    for new_field in new_schema.fields:
        if new_field.required and not old_schema.has(new_field.name):
            breaks.append(f"field {new_field.name} required and new")
    return breaks
```

### 10.3 Schema drift detection (런타임)

```text
PUBLIC_API_FETCH 노드 실행
  ↓
응답 sample 5건 → 자동 schema 추론 (jsonschema-inference)
  ↓
contract.schema_yaml 과 diff
  ↓
breaking change 감지 시:
  - severity=ERROR → run FAILED + ADMIN 알림
  - severity=WARN → run SUCCESS but report 보고
  - 정상이면 nothing
```

---

## 11. Wave 별 작업 순서 (10 weeks)

### Wave 1A — Source 일반화 1차 (W1) ★ 사용자 § 15.8 보완 — 분할
**목표**: 가장 시급한 3종 (사용자 시나리오 § 8.2 / § 8.4 / § 2.5) 만 먼저 구현.
- [ ] migration: `audit.inbound_event` + `domain.inbound_channel` 테이블
- [ ] backend: `POST /v1/inbound/{channel_code}` (HMAC SHA256 + replay ±5분 + idempotency)
- [ ] backend: 3 source 노드 dispatcher 추가:
  - `WEBHOOK_INGEST` (외부 크롤링 / 일반 push)
  - `FILE_UPLOAD_INGEST` (소상공인 multipart upload)
  - `DB_INCREMENTAL_FETCH` (Canvas 노드화 — `db_incremental.py` 활용)
- [ ] backend: HMAC 검증 utility (`app/core/hmac_verifier.py`)
- [ ] frontend: NodePaletteV2 의 DATA SOURCES 카테고리에 3종 노출
- [ ] frontend: 새 `pages/v2/InboundChannelDesigner.tsx` — 외부 push 채널 등록 UI
- [ ] **시연**: webhook 채널 등록 → curl push → workflow 자동 trigger → mart 적재
- [ ] **회귀**: PUBLIC_API_FETCH 4박스 e2e (KAMIS) 그대로 통과

### Wave 1B — Source 일반화 2차 (W2)
**목표**: Wave 1A 의 패턴을 재사용해 4종 추가. *같은 receiver / dispatcher 패턴 확장*.
- [ ] backend: 4 source 노드 추가:
  - `OCR_RESULT_INGEST` (외부 OCR 업체 push — 표준 OCR 응답 schema 정의)
  - `CRAWLER_RESULT_INGEST` (외부 크롤러 업체 push)
  - `CDC_EVENT_FETCH` (Canvas 노드화 — `wal2json_consumer.py` 활용)
- [ ] backend: 기존 `OCR_TRANSFORM` (우리가 OCR 호출) vs `OCR_RESULT_INGEST` (외부가 push) 명확히 구분 docs
- [ ] frontend: palette 7종 모두 노출 + drawer
- [ ] **시연**: OCR 업체 모킹 → push → 분류 → mart 적재 / CDC slot → row 변경 → trigger
- [ ] **mTLS 옵션 문서화** (사용자 § 15.1 — *금융/대기업 채널 한정*. 본 Phase 코드 변경 없음)

### Wave 2 — 자산 version pinning (W2~W3) ★ 사용자 § 15.2

**Auto-fork 정책 (사용자 § 15.2 결정)**:

- **UI**: PUBLISHED/APPROVED 자산 수정 시도 → modal 확인 *"운영 중 자산입니다.
  새 DRAFT v{N+1} 으로 분기할까요?"* → 사용자 confirm 후 fork
- **API**: PATCH 요청에 `?auto_fork=true` 옵션 지원 — automation/test 용
- 사용자 confirm 없이 silent fork 는 *금지* (운영자 의도 보호)

작업:
- [ ] backend: 8 entity 모두 PUBLISHED/APPROVED 수정 시 422 + `{"action": "fork_required", "next_version": N+1}` 응답
- [ ] backend: API `?auto_fork=true` 옵션 추가
- [ ] backend: workflow_definition 의 node_definition.config_json 에 자산 version 강제 기재
- [ ] backend: pipeline_run 에 사용된 자산 version snapshot 저장 (`run.pipeline_run.asset_versions_json`)
- [ ] frontend: 자산 편집 dialog 에 fork 확인 modal — "v{n+1} 으로 분기할까요?"
- [ ] frontend: 자산 편집 시 "v{n} 으로 fork됨" 토스트
- [ ] frontend: workflow 상세에 "사용 중인 자산 version" 박스
- [ ] **시연**: PUBLISHED mapping 수정 시도 → modal → confirm → DRAFT v{n+1} 생성 → 운영 workflow 는 v{n} 그대로

### Wave 3 — Provider Registry primary path (W3~W4) ★ 사용자 § 15.8 보완 — shadow 기간 명시

**기본 정책 (사용자 § 15.3)**: Provider 추상화 우선. seed = OpenAI + Clova HCX
(Anthropic 은 2차 provider 로 열어둠).

**Cutover 절차 — Phase 5.2.5 의 shadow_run 패턴 재사용**:

```
[Day 1~7]  shadow 모드 — primary 와 secondary 양쪽 호출, 결과 diff 만 audit.shadow_diff
[Day 7]    diff 보고 검토 → 정확도/지연/비용 OK 면 ADMIN cutover 결정
[Day 8]    primary 활성, secondary 는 fallback_provider 로 자동 강등
[+30일]    audit.provider_usage 로 운영 안정성 추적
```

작업:
- [ ] backend: `app.domain.providers.factory` 를 OCR_TRANSFORM / CRAWL_FETCH 의 primary path 로 전환
- [ ] backend: 신규 provider_kind: `LLM_CLASSIFY` / `ADDRESS_NORMALIZE` /
      `PRODUCT_CANONICALIZE` / `CODE_LOOKUP`
- [ ] backend: `LLM_CLASSIFY` seed — OpenAI + Clova HCX (각각 implementation_type 으로)
- [ ] backend: `audit.provider_usage` 테이블 + 비용 집계
- [ ] backend: shadow_run 모드 — primary + secondary 동시 호출 + diff audit
- [ ] frontend: Transform Designer 의 Provider 탭 → primary path 표시 + cost graph
- [ ] frontend: 캔버스 drawer 에 fallback_provider 선택
- [ ] frontend: shadow diff dashboard (`/v2/operations/provider-shadow`)
- [ ] **acceptance**:
  - shadow 1주 → diff 보고 → cutover → 1주 운영 후 문제 없음
  - LLM_CLASSIFY 노드 1개로 OCR 결과 → 카테고리 분류 → confidence < 0.7 시 검수 큐
  - Anthropic 추가 시 코드 수정 없이 새 implementation_type 으로만 등록 가능

### Wave 4 — Sandbox dry-run + DQ catalog 확장 (W4~W5) ★ 사용자 § 15.4 + § 15.8 보완

**Sandbox 환경 분리 정책 (사용자 § 15.4 결정)**:

| 환경 | sandbox 위치 | 이유 |
|---|---|---|
| local / dev | 메인 DB 의 `sandbox_<run_id>_*` 임시 schema | 빠른 반복, 격리 부담 ↓ |
| staging | **read replica** + 임시 schema (replica 안에서) | 운영 부하 격리 |
| production | **read replica** + 임시 schema **— 메인 DB 임시 schema 금지** | 운영 데이터 실수 방지 |

> **운영 보호 원칙**: production 환경에서는 *어떤 경우에도 메인 DB 에 임시
> schema 를 만들지 않는다*. settings 의 `is_production==True` 면 sandbox 의 target
> URL 이 read replica 가 아니면 즉시 422 error.

작업:
- [ ] backend: `/v2/dryrun/workflow/{id}/sandbox` — DAG 전체 sandbox session
- [ ] backend: settings 에 `sandbox_database_url` 추가 (production 필수)
- [ ] backend: production 가드 — `if settings.is_production and not settings.sandbox_database_url: raise`
- [ ] backend: 노드 간 *실제 sandbox table* 데이터 흐름 (각 노드 result 1000건 cache)
- [ ] backend: mart impact preview (`INSERT N / UPDATE M / SKIP K`)
- [ ] backend: DQ rule 5종 추가 (freshness / anomaly_zscore / anomaly_iqr / drift_kl /
      referential_integrity)
- [ ] frontend: DryRunResults 페이지에 input/output sample table + mart diff 노출
- [ ] **시연**: 4박스 workflow → sandbox → 박스별 5건 sample + mart 영향도 정확히 표시
- [ ] **운영 보호 회귀**: production 에서 sandbox_database_url 미설정 시 sandbox 호출 거부 확인

### Wave 5 — Operations Dashboard + node partial replay (W5~W6) ★ 사용자 § 15.5

**갱신 주기 정책 (사용자 § 15.5 결정)**:

| 화면 | 갱신 방식 | 이유 |
|---|---|---|
| 요약 dashboard (15~20 채널 한눈) | **30s polling** | 단순 + 안정. 다수 client 동시 접속 시 backend 부하 ↓ |
| 특정 run 상세 | **SSE** (기존) | 실시간 box-by-box 진행 |
| 노드별 metric (heatmap) | 30s polling | aggregate 쿼리 = polling 적합 |

작업:
- [ ] backend: `POST /v1/pipelines/runs/{run_id}/replay-from?node_key=...` (upstream cache 활용)
- [ ] backend: aggregated channel metrics endpoint (`/v2/operations/summary`) — 30s cacheable
- [ ] backend: per-node metrics (`/v2/operations/heatmap?workflow_id=...&days=7`)
- [ ] frontend: 새 페이지 `/v2/operations/dashboard` (TanStack Query refetchInterval=30000)
- [ ] frontend: run 상세 페이지 (기존 `PipelineRunDetail`) 에 "이 노드부터 재실행" 버튼
- [ ] **시연**: 8개 workflow 동시 운영 + dashboard 에서 한눈 + 실패 노드 재실행

### Wave 6 — Event-driven trigger (W6~W7) ★ 사용자 § 15.6

**처리량 결정 (사용자 § 15.6)**: **Kafka 미도입**. Redis Streams + Dramatiq + outbox
유지. ADR-0020 트리거 (지속 lag / 1주 이상 replay 요구 / 외부 CDC 대규모 / 초당
수백~수천 event) 충족 시에만 재검토.

작업:
- [ ] migration: `wf.workflow_event_binding` + `wf.workflow_definition.trigger_kind` 컬럼
- [ ] backend: outbox dispatcher (Dramatiq actor) — outbox poll → workflow trigger
- [ ] backend: inbound event → outbox 자동 publish
- [ ] backend: 채널별 rate limit (예: 100 event/min/channel) — DLQ 강제 라우팅
- [ ] frontend: ETL Canvas 의 toolbar 에 trigger_kind 선택 (cron / event / manual)
- [ ] frontend: 이벤트 binding 편집 UI (channel_code → workflow 선택)
- [ ] **시연**: 소상공인 업로드 → 5초 내 workflow trigger → 30초 내 mart 적재
- [ ] **모니터링 추가**: outbox lag (last_published_at vs now) > 30s 시 alert

### Wave 7 — Schema Evolution + Data Contract (W7~W8)
- [ ] migration: `source_contract` 의 schema_version → semver 분할
- [ ] backend: `/v2/contracts/{id}/check-evolution` (BACKWARD 자동 검증)
- [ ] backend: PUBLIC_API_FETCH 노드 실행 시 schema drift detection (severity 별 routing)
- [ ] frontend: Source Workbench 에 schema diff 시각화
- [ ] **시연**: KAMIS API 응답에 새 필드 추가 → minor++ 자동 감지 → workflow 영향 없음

### Wave 8 — Bronze/Silver/Gold 명명 표준화 + Lineage 기초 (W8) — Phase 7.5 분리 가능

> **사용자 § 15.7 결정**: Wave 8~9 는 일정 여유 부족 시 **Phase 7.5 또는 Phase 8** 로
> 분리 가능. 핵심 acceptance 는 Wave 1~6 만으로 충족.

- [ ] migration: `<domain>_raw` (Bronze) / `<domain>_stg` (Silver) / `<domain>_mart`
      (Gold) 강제 표준 (sql_guard 의 화이트리스트로)
- [ ] backend: 각 run 의 input/output table 자동 기록 (`audit.run_lineage`)
- [ ] backend: `/v2/lineage/asset/{type}/{id}` — 어떤 workflow 가 사용 중인지 reverse lookup
- [ ] frontend: 자산 편집 시 "이 자산 사용 중인 workflow N개" 표시
- [ ] **시연**: mapping 수정 시도 → 사용 중인 workflow 3개 표시 → 자동 fork

### Wave 9 — Replay / Backfill UX 완성 (W9~W10) — Phase 7.5 분리 가능

- [ ] frontend: `/v2/operations/backfill` — 날짜 범위 + chunk 진행률
- [ ] backend: backfill 의 chunk 단위 retry (이미 backend 있음, UX 만)
- [ ] frontend: replay 사유 (reason) 입력 + 결과 비교 보고서
- [ ] **시연**: 7일치 backfill → 진행률 실시간 + 청크 1개 실패 시 해당 청크만 재시도

### Wave 10 — Phase 8 Kickoff (도메인 특화) (W10~)
공용 기능이 *모두 완성된 후* 아래로 넘어간다 — 본 Phase 7 의 *out of scope*.

- 유통사 4개 API connector 등록 (KAMIS 외 추가 3개)
- 행사가 / 재고 SCD2 모델 + LOAD_TARGET scd_type_2 구현
- 상품 규격 normalizer 함수 (weight / unit / grade)
- 가격 변경 이력 추적 패턴
- 배달 서비스 연계 마트 구조

---

## 12. 위험 + 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| **Wave 1 inbound endpoint 가 너무 큰 PR 됨** | 일정 지연 | WEBHOOK_INGEST 1종만 먼저 W1 종료 시 시연. 나머지 6종은 W2 분할 |
| **Wave 2 auto-fork 가 기존 운영 workflow 깨뜨림** | 회귀 | migration 0049 적용 시 *기존 자산 모두 v1 으로 통일* + 명시적 cutover flag |
| **Wave 3 provider primary 전환 시 OCR 정확도 저하** | 운영 | shadow_run (Phase 5.2.5) 로 v1 vs primary 비교 후 cutover |
| **Wave 4 sandbox session 이 실 DB 부하** | 운영 | sandbox 는 read-only mirror DB 사용 (NCP read replica 활용) |
| **Wave 6 event 폭주 시 workflow 큐 적체** | SLA | rate limit per channel_code + DLQ 강제 |
| **Wave 7 schema drift 가 false positive** | 운영자 피로 | severity 단계별 routing — 처음엔 모두 WARN 만 |

---

## 13. 산출물 예상

### 신규 backend
- `app/api/v1/inbound.py` (Wave 1) — 4 inbound endpoint
- `app/domain/inbound/` — envelope + receiver + dispatcher
- `app/domain/nodes_v2/webhook_ingest.py` / `file_upload_ingest.py` /
  `ocr_result_ingest.py` / `crawler_result_ingest.py` / `db_incremental_fetch.py` /
  `cdc_event_fetch.py` (Wave 1)
- `app/api/v2/lineage.py` (Wave 8)
- `app/api/v2/operations.py` — channel summary + replay-from (Wave 5)
- `app/domain/providers/factory.py` 확장 (Wave 3)
- `app/domain/dq/anomaly.py` — drift / freshness / zscore (Wave 4)
- `app/domain/contract/evolution.py` — semver + breaking detect (Wave 7)
- `app/domain/sandbox/` — DAG sandbox session (Wave 4)
- `app/workers/event_dispatcher.py` — outbox → workflow trigger (Wave 6)

### 신규 frontend
- `pages/v2/OperationsDashboard.tsx` (Wave 5)
- `pages/v2/InboundChannelDesigner.tsx` (Wave 1) — 외부 push 채널 등록 UI
- `pages/v2/AssetVersionExplorer.tsx` (Wave 8)
- `pages/v2/BackfillWizard.tsx` (Wave 9)
- 기존 페이지 보강:
  - `EtlCanvasV2.tsx` — 7 source 노드 추가, trigger_kind 선택, replay-from 버튼
  - `DryRunResults.tsx` — sandbox 결과 + sample table + mart diff
  - 모든 designer — fork 토스트 + version pinning 표시

### 신규 migration
- `0049_inbound_envelope.py` — `audit.inbound_event` + `domain.inbound_channel`
- `0050_node_type_phase7.py` — node_type CHECK 에 6종 추가 (WEBHOOK_INGEST / ...)
- `0051_asset_version_pinning.py` — workflow_definition 자식 자산 version 강제
- `0052_workflow_event_binding.py` — Wave 6
- `0053_source_contract_semver.py` — Wave 7
- `0054_provider_usage_log.py` — Wave 3
- `0055_run_lineage.py` — Wave 8

### 신규 ADR
- ADR-0022 — Inbound Push Receiver 표준 (HMAC + idempotency)
- ADR-0023 — Asset Version Pinning + auto-fork policy
- ADR-0024 — Provider Registry primary path 전환
- ADR-0025 — Sandbox DAG execution
- ADR-0026 — Event-driven Trigger
- ADR-0027 — Schema Evolution policy
- ADR-0028 — Phase 7 회고 + Phase 8 backlog

### 신규 docs
- `docs/onboarding/07_external_push_setup.md` — 외부 업체에게 줄 push 가이드
- `docs/onboarding/08_provider_authoring.md` — 새 provider 등록 절차
- `docs/operations/dashboard_guide.md`
- `docs/architecture/data_contract_evolution.md`

---

## 14. Phase 8 backlog (도메인 특화 — 본 Phase 의 out of scope)

Phase 7 가 완료되면 다음을 진행한다 (사용자 § 1 ~ § 11 의 *도메인 의존* 부분).

| 항목 | 출처 |
|---|---|
| 유통사 4개 API connector 등록 + KAMIS 외 cert key 발급 | § 2.1 |
| 행사가 / 재고 SCD2 LOAD_TARGET 모드 구현 | § 10.3 |
| 상품 규격 normalizer (weight / unit / grade / 원산지) | § 3.4 |
| GS1 GDSN 연계 표준코드 매핑 (선택) | § 3.4 |
| LLM_CLASSIFY 노드의 OCR 분류 prompt 표준화 | § 8.3 |
| 외부 업체 onboarding (크롤러 / OCR push 채널 1건씩) | § 8.2 / 8.3 |
| 소상공인 업로드 web 화면 (cloudsourcing) | § 8.4 |
| 배달 서비스 연계용 mart 구조 (매장/품절/거리) | § 10.4 |
| Lineage Viewer 시각화 (OpenLineage 통합) | Wave 8 후속 |
| AI-assisted Field Mapping (Phase 6 backlog 에서 이월) | — |
| Backfill UI 가속 (Phase 6 backlog 에서 이월) | — |

---

## 15. 검토 결정안 (사용자 답변 반영)

작성일: 2026-04-26

### 15.1 Inbound 인증 방식
> **1차는 HMAC SHA256 + replay window ±5분.** mTLS 는 *선택 옵션* 으로 문서화.
> 외부 업체 연동 초기에 mTLS 까지 강제하면 진입장벽이 큼. 금융/대기업 전용
> 채널에서만 mTLS 추가.

**적용**: Wave 1A 의 `POST /v1/inbound/{channel_code}` 는 HMAC 만. mTLS 는 별도
ADR-0022 부록으로 *옵션* 명시.

### 15.2 Auto-fork 정책
> **사용자 confirm 후 fork.** 단, API 호출은 `auto_fork=true` 옵션 지원. UI 에서는
> "운영 중 자산입니다. 새 DRAFT vN으로 분기할까요?" 확인이 안전.

**적용**: Wave 2 의 frontend 에 fork modal 강제. backend 는 422 응답 +
`{"action": "fork_required", "next_version": N+1}` 반환.

### 15.3 LLM 우선 provider
> **Provider 추상화 우선, 기본 seed 는 OpenAI + Clova HCX.** 국내/NCP 친화는
> Clova HCX, JSON Schema/structured output 성숙도는 OpenAI 가 강함. Anthropic 은
> 2차 provider 로 열어둠.

**적용**: Wave 3 의 `LLM_CLASSIFY` provider_kind 에 implementation_type 으로
`openai` + `clova_hcx` 두 종 seed. Anthropic 은 implementation_type 만 추가하면
즉시 사용 가능 구조 (코드 변경 0).

### 15.4 Sandbox 환경 분리
> **개발/로컬은 임시 schema, staging/prod 는 read replica + 임시 schema.**
> 운영 DB 부하와 실수 위험을 줄이려면 replica 가 글로벌 표준에 더 가까움.

**적용**: Wave 4 의 sandbox 매트릭스 표 (§ Wave 4 spec). production 가드 강제.

### 15.5 Dashboard 갱신 주기
> **요약 dashboard 는 30s polling, run detail 은 SSE.** 전체 15~20개 workflow 현황은
> polling 이 단순하고 안정적. 특정 실행 상세만 실시간 SSE 가 맞음.

**적용**: Wave 5 의 dashboard 매트릭스 표 (§ Wave 5 spec).

### 15.6 Event 처리량 — Kafka 도입 트리거
> **지금은 Kafka 도입 X.** Redis Streams / Dramatiq 유지. 단, ADR-0020 트리거
> 충족 시 Kafka 검토. 예: 지속 lag, 1주 이상 replay 요구, 외부 CDC 대규모,
> 초당 수백~수천 event.

**적용**: Wave 6 의 명시 + outbox lag 알림 추가. ADR-0020 트리거 모니터링은
Phase 7.5 backlog.

### 15.7 일정 — 10주 적정성
> **MVP 기준 10주 적정.** 다만 **Wave 1+2+4+5+6 이 핵심**이고, Wave 8~9 는
> 여유 없으면 Phase 7.5 또는 Phase 8 전환 가능.

**적용**: Wave 8/9 헤더에 *"Phase 7.5 분리 가능"* 표시. Phase 7 핵심 = Wave 1~6.

### 15.8 Acceptance — 시나리오 충분성
> **핵심 acceptance 로는 충분.** 단, *"API Pull 1건"* 을 추가해서 5개 시나리오로
> 만드는 게 더 좋음. 기존 KAMIS / PUBLIC_API_FETCH 회귀를 공용 기능 기준으로
> 계속 보장해야 함.

**적용**: § 2.3 acceptance 를 4 → **5개 시나리오** 로 확장 (5번째 = Phase 6
KAMIS 회귀). 매 Wave 종료 시 회귀 테스트 통과 의무화.

---

## 15.x 사용자 § 15 외 추가 보완 사항 (사용자 제안)

### 15A. Wave 1 분할
> "7개 source 노드를 한 번에 다 만들면 커질 수 있어. WEBHOOK / FILE_UPLOAD /
> DB_INCREMENTAL 3개를 1차로 잡고, OCR/CRAWLER/CDC 는 같은 패턴으로 확장."

**적용**: Wave 1 → **Wave 1A (3종) + Wave 1B (4종)** 분할. § 11 참조.

### 15B. Provider Primary Path 의 shadow 기간 명시
> "OCR/Crawler/LLM provider 를 바로 primary 로 바꾸면 위험하니, *'shadow 1주 →
> diff 확인 → cutover'* 를 acceptance 에 넣는 게 좋아."

**적용**: Wave 3 의 cutover 절차 박스 추가 + acceptance 명시. § Wave 3 참조.

### 15C. Sandbox 운영 보호 원칙 강화
> "*운영 환경에서는 main DB 임시 schema 금지, read replica 또는 isolated sandbox DB
> 권장*."

**적용**: Wave 4 에 production 가드 추가 — `is_production && !sandbox_database_url`
이면 sandbox 호출 자체 거부. § Wave 4 참조.

### 15D. API Pull 회귀 acceptance
> "현재 4개 시나리오는 push/upload/version/replay 중심이라, 이미 만든
> PUBLIC_API_FETCH 가 Phase 7 후에도 깨지지 않는지 보장하는 항목이 있으면 좋아."

**적용**: § 2.3 acceptance 에 5번째 시나리오 (KAMIS PUBLIC_API_FETCH 회귀) 추가.

---

## 16. 다음 액션

- [x] 사용자: § 15 의 8개 검토 포인트 답변 (2026-04-26 완료)
- [x] Claude: 답변 반영 + § 15 갱신 + 보완 4종 적용 (Wave 1 분할 / Provider shadow /
      Sandbox 운영 보호 / API Pull 회귀)
- [ ] **Claude: Wave 1A 부터 commit-by-commit 으로 진행** (즉시 시작 가능)
- [ ] 진행 중 새 사실 발견 시 본 문서 *살아있는 spec* 으로 갱신

### Wave 1A 진입 즉시 작업 항목

```
Step 1) migration 0049: audit.inbound_event + domain.inbound_channel 테이블
Step 2) backend: app/core/hmac_verifier.py (HMAC SHA256 + replay window)
Step 3) backend: app/api/v1/inbound.py — POST /v1/inbound/{channel_code}
Step 4) backend: nodes_v2/webhook_ingest.py / file_upload_ingest.py /
                 db_incremental_fetch.py (dispatcher 등록)
Step 5) frontend: api/v2/inbound.ts + pages/v2/InboundChannelDesigner.tsx
Step 6) frontend: NodePaletteV2 의 DATA SOURCES 카테고리에 3종 노출
Step 7) 회귀: KAMIS 13분 시나리오 통과 확인
Step 8) commit + push + ADR-0022 (HMAC + idempotency 표준)
```

**예상**: Wave 1A 1주 (W1) 완료 후 사용자 확인 → Wave 1B 진입.

---

## 17. 참조

- [PHASE_5_GENERIC_PLATFORM.md](./PHASE_5_GENERIC_PLATFORM.md) — generic platform 1차
- [PHASE_5_PROMPTS.md](./PHASE_5_PROMPTS.md) — STEP 1~12 실행 가이드
- [PHASE_6_PRODUCT_UX.md](./PHASE_6_PRODUCT_UX.md) — 6 workbench + Canvas + Dry-run
- [ADR-0018](../adr/0018-phase5-v2-generic-retrospective.md) — Phase 5 회고
- [ADR-0019](../adr/0019-phase5-abstraction-validation-pos.md) — POS 추상화 검증
- [ADR-0020](../adr/0020-kafka-introduction-triggers.md) — Kafka 도입 조건
- [ADR-0021](../adr/0021-phase6-product-ux.md) — Phase 6 회고

### 글로벌 표준 참조

- **Open Data Contract Standard** — https://github.com/bitol-io/open-data-contract-standard
- **Singer / Tap / Target spec** — https://www.singer.io/
- **Airbyte Connector spec** — https://docs.airbyte.com/connector-development/
- **dbt model contract** — https://docs.getdbt.com/docs/collaborate/govern/model-contracts
- **Great Expectations** — https://greatexpectations.io/
- **Soda Data Quality** — https://www.soda.io/
- **OpenLineage** — https://openlineage.io/
- **Stripe Webhook** — https://stripe.com/docs/webhooks
- **Snowflake Snowpipe** — auto ingest pattern
- **Databricks Medallion** — Bronze/Silver/Gold layering
- **Microservices Patterns: Outbox** — Chris Richardson
- **OpenAI Function Calling + JSON Schema** — structured LLM
- **GS1 GDSN** — 글로벌 상품 데이터 표준
