# Phase 6 — Field Validation: 공공 OpenAPI + 사용자 업로드 실증

**전제:** Phase 5 v2 Generic 이 최소 1개 도메인에서 동작. source contract / mapping /
mart designer / DQ rule / LOAD_TARGET / Designer dry-run 이 준비되어 있다.

**목표:** 실제 공공데이터포털 OpenAPI 와 사용자 업로드 데이터를 v2 위에서 수집해 raw → staging
→ DQ → mart → 서비스 API 까지 end-to-end 로 검증한다. Phase 6 는 기능 추가보다 **현장성 검증**
단계다.

**기간 목표:** 6~8주

**성공 기준 (DoD):**
1. 공공데이터포털 OpenAPI 1~2개를 실제 서비스키로 연동하고, 스케줄 수집부터 mart 적재까지
   자동화한다.
2. 사용자 업로드 샘플 페이지에서 CSV/JSON/XLSX/이미지 중 최소 2종을 업로드하고, source
   contract 검증 + raw 보존 + DQ 결과를 확인할 수 있다.
3. 같은 v2 공정으로 **공공 API 데이터**와 **사용자 업로드 데이터**를 모두 처리한다.
4. DQ 실패 / schema mismatch / API rate limit / 사용자 파일 오류가 운영자가 이해 가능한
   메시지와 재처리 경로로 노출된다.
5. 실증 결과를 바탕으로 Phase 5 의 generic schema, Designer UX, 성능 가드레일을 수정할
   backlog 를 확정한다.

---

## 6.0 실증 가설

Phase 5 의 핵심 가설:

> "도메인별 코드를 새로 짜지 않고, source contract + mapping + mart + DQ + load policy 만
> 설계하면 새 데이터 수집 파이프라인을 만들 수 있다."

Phase 6 는 이 가설을 실제 데이터로 검증한다.

검증해야 할 질문:

| 질문 | 검증 방법 |
|---|---|
| 공공 OpenAPI 명세가 v2 source contract 로 충분히 표현되는가? | API 응답 샘플 → schema 생성 → validation |
| 제공처마다 다른 필드명을 mapping UI 로 처리할 수 있는가? | 원본 필드 → staging/mart 필드 매핑 |
| 사용자 업로드 데이터는 API 데이터와 같은 공정으로 처리 가능한가? | upload source 를 API source 와 동일 contract/mapping/DQ 로 처리 |
| DQ rule 을 운영자가 이해하고 조정할 수 있는가? | DQ 실패 sample / rule editor / 재실행 |
| 성능 가드레일이 실제 backfill/polling 에 충분한가? | rate limit, batch size, chunked backfill 측정 |

---

## 6.1 대상 데이터 선정

### 6.1.1 공공데이터포털 OpenAPI 후보

후보는 실제 개발 시작 시점에 공공데이터포털에서 최신 상태를 다시 확인한다. OpenAPI 는 폐기,
트래픽 제한, 심의 유형, 응답 필드가 바뀔 수 있으므로 문서에 고정하지 않는다.

우선순위:

| 우선순위 | 후보 유형 | 이유 |
|---|---|---|
| 1 | 농축산물/식품/가격/시장 관련 OpenAPI | v1 agri 도메인과 비교 검증 가능 |
| 2 | 지역 상권/업소/사업자/매장 정보 OpenAPI | master/dimension 모델 검증 |
| 3 | 날씨/환경/교통 같은 시계열 OpenAPI | generic fact/event 모델 검증 |

선정 기준:

- REST OpenAPI 이고 서비스키 기반 호출 가능.
- JSON 또는 XML 응답을 제공.
- 최소 1개 날짜/지역/페이지 파라미터가 있어 polling/backfill 을 검증할 수 있음.
- 일일 트래픽 제한이 실증 테스트에 충분함.
- 개인정보 또는 민감정보가 포함되지 않거나 마스킹 가능.

### 6.1.2 사용자 업로드 데이터 후보

사용자 업로드는 "crowdsourcing" 경로의 실증이다. 사용자가 직접 파일을 올리고, 플랫폼은 이를
source 로 취급한다.

초기 지원:

| 유형 | 예 | 처리 |
|---|---|---|
| CSV | 매장별 가격/재고 샘플 | delimiter/header/type inference |
| JSON | 외부 API 응답 샘플 | schema inference + contract 생성 |
| XLSX | 운영자가 받은 엑셀 자료 | 첫 sheet preview + column mapping |
| IMAGE/PDF | 영수증/전단 샘플 | OCR queue 로 전송, 개인정보 마스킹 |

업로드 파일은 항상 raw 로 보존하고, 변환 실패 시에도 삭제하지 않는다. 다만 개인정보가 포함될 수
있으므로 업로드 전 고지와 OCR/텍스트 마스킹 정책을 함께 제공한다.

---

## 6.2 End-to-End 공정

```
[공공 OpenAPI / 사용자 업로드]
  → source contract validation
  → raw.raw_object / Object Storage 보존
  → field mapping
  → staging table 적재
  → DQ_CHECK
  → LOAD_TARGET
  → mart table
  → lineage / metrics / audit
  → internal API 또는 public preview API
```

공공 OpenAPI 와 사용자 업로드는 수집 입구만 다르고, 이후 공정은 같아야 한다.

| 단계 | 공공 OpenAPI | 사용자 업로드 |
|---|---|---|
| Source | `PUBLIC_API` connector | `USER_UPLOAD` connector |
| Auth | data.go.kr service key / provider key | 로그인 사용자 + upload permission |
| Raw | response body + request params | file object + parsed preview |
| Contract | response schema | uploaded file schema |
| Mapping | API field mapping | column/JSON path mapping |
| DQ | same rule registry | same rule registry |
| Mart | same LOAD_TARGET | same LOAD_TARGET |
| Audit | request params / run id | uploader / file hash / run id |

---

## 6.3 작업 단위 체크리스트

### 6.3.1 Public OpenAPI Connector [W1~W2]

- [ ] `backend/app/connectors/public_api.py` — service key, query params, pagination, retry,
  timeout, rate limit 지원.
- [ ] `domain.source_contract` 에 public API response schema 등록.
- [ ] XML 응답이면 JSON 형태로 normalize 하는 adapter 추가.
- [ ] request params / response status / provider error 를 raw metadata 에 저장.
- [ ] provider rate limit 초과 시 retry 하지 않고 `THROTTLED` 상태 + 다음 스케줄로 이월.
- [ ] tests: sample response fixture 로 schema validation / pagination / error handling 검증.

### 6.3.2 Public API Pipeline Template [W2]

- [ ] Designer template: `PUBLIC_API_POLLING → MAP_FIELDS → DQ_CHECK → LOAD_TARGET → NOTIFY`.
- [ ] Backfill template: 날짜 범위 파라미터를 query params 로 펼쳐 chunk 실행.
- [ ] DQ 기본 rule: row_count_min, required fields, unique business key, observed_at parse.
- [ ] mart 예시: `mart.public_api_observation_fact` 또는 도메인별 target table.
- [ ] docs: 서비스키 발급/등록/보안 주의사항.

### 6.3.3 사용자 업로드 샘플 페이지 [W2~W4]

- [ ] `frontend/src/pages/DataUploadPage.tsx` 신규.
- [ ] 지원 모드: CSV / JSON / XLSX / IMAGE/PDF.
- [ ] 업로드 전 source/domain 선택.
- [ ] 업로드 후 first N rows preview.
- [ ] schema inference 결과 표시: column name, inferred type, null count, sample values.
- [ ] field mapping UI 로 이동: source column/path → target field.
- [ ] DQ rule 추천: required candidate, unique candidate, range candidate.
- [ ] "Dry-run" 버튼: raw 저장 + staging preview + DQ 실행, mart 적재 없음.
- [ ] "Publish run" 버튼: 승인된 mapping/DQ 로 실제 LOAD_TARGET 실행.
- [ ] 업로드 이력: uploader, file name, content_hash, raw_object_id, DQ status.

### 6.3.4 Upload Backend [W3~W4]

- [ ] `POST /v2/uploads` — multipart upload + domain/source 연결.
- [ ] `GET /v2/uploads/{upload_id}/preview` — inferred schema + sample rows.
- [ ] `POST /v2/uploads/{upload_id}/dry-run` — staging temp table + DQ only.
- [ ] `POST /v2/uploads/{upload_id}/publish-run` — approved mapping 기준 pipeline run 생성.
- [ ] CSV parser: encoding detection, delimiter detection, header normalization.
- [ ] XLSX parser: 첫 sheet 우선, sheet 선택은 후속.
- [ ] JSON parser: object list / single object / nested path 지원.
- [ ] IMAGE/PDF: 기존 OCR worker queue 로 연결.
- [ ] 파일 크기 제한, 확장자 allowlist, virus scan hook placeholder.

### 6.3.5 DQ + Mart 실증 [W4~W5]

- [ ] DQ rule registry 에 실증용 rule 5종 이상 등록.
- [ ] DQ 실패 row sample viewer 와 연결.
- [ ] LOAD_TARGET 으로 append-only fact 와 UPSERT master 각각 1회 이상 검증.
- [ ] schema mismatch 발생 시 raw 보존 + processing HOLD + 수정 후 재실행.
- [ ] lineage: upload/API raw_object_id → staging table → mart row 까지 추적 가능.

### 6.3.6 운영/성능 실증 [W5~W6]

- [ ] 공공 API polling 1일 이상 연속 실행.
- [ ] API rate limit / provider error / network timeout 관측.
- [ ] upload 100건, 1만 row CSV, 10MB 파일 baseline 측정.
- [ ] worker lag, DQ duration, LOAD_TARGET rows/sec dashboard 기록.
- [ ] backfill 7일치 dry-run + publish-run 검증.
- [ ] 실패 재처리: DQ rule 수정 → 같은 raw 로 재실행.

### 6.3.7 실증 회고 + Phase 5 보정 [W6~W8]

- [ ] 실증 결과 리포트 작성: 성공/실패/병목/UX 마찰.
- [ ] Phase 5 generic schema 에 필요한 변경 PR 목록화.
- [ ] Designer UX 개선 backlog 확정.
- [ ] 공공 API 연동 운영 runbook 작성.
- [ ] 사용자 업로드 개인정보/보안 정책 보강.
- [ ] ADR-0019: Field Validation 결과와 v2 보정 결정.

---

## 6.4 사용자 업로드 UX 초안

업로드 화면은 설명 페이지가 아니라 실제 작업 화면이어야 한다.

화면 흐름:

```
1. Domain / Source 선택
2. 파일 업로드
3. Preview + schema inference
4. Field mapping
5. DQ rule 선택/추천
6. Dry-run
7. Publish run
8. 결과 확인: raw / staging / DQ / mart / lineage
```

필수 UI:

| UI | 목적 |
|---|---|
| Dropzone | CSV/JSON/XLSX/IMAGE/PDF 업로드 |
| Preview table | first N rows, null count, type inference 표시 |
| Mapping designer | source column/path 를 target field 로 연결 |
| DQ recommendation panel | required/unique/range 후보 rule 제안 |
| Dry-run result | row_count, failed DQ, sample errors, expected target rows |
| Publish checklist | contract, mapping, DQ, target, performance guard 통과 확인 |
| Run timeline | raw 저장 → parsing → DQ → LOAD_TARGET 단계 상태 |

가드레일:

- 업로드 즉시 mart 적재 금지. 기본은 dry-run.
- PII 후보 컬럼명(`name`, `phone`, `email`, `address`, `주민`, `전화`) 감지 시 경고.
- 이미지/PDF 는 OCR 전 개인정보 포함 가능성 고지.
- 같은 content_hash 파일 재업로드 시 기존 raw_object 와 비교해 dedup 안내.

---

## 6.5 성능 / 보안 / 운영 기준

### 성능 기준

| 항목 | 목표 |
|---|---|
| 10MB CSV preview | 10초 이하 |
| 1만 row dry-run | 60초 이하 |
| Public API polling | provider rate limit 내 안정 실행 |
| DQ custom_sql | 30초 timeout |
| LOAD_TARGET | rows/sec baseline 기록, 대용량은 chunked load |
| Backfill | chunk 단위 resume 가능 |

### 보안 기준

- 공공 API service key 는 `.env`/Secret Manager 에만 저장. DB 에 평문 저장 금지.
- 업로드 파일은 Object Storage private bucket 에 저장.
- presigned download 는 권한 확인 후 짧은 TTL.
- upload audit: uploader, ip, file name, content_hash, raw_object_id 기록.
- OCR/업로드 텍스트는 PII scrubber 를 통과.

### 운영 기준

- provider 별 장애/응답 지연/트래픽 초과를 dashboard 에 표시.
- 공공 API 명세 변경 시 contract compatibility alert.
- 사용자 업로드 실패는 "파일 오류", "schema 오류", "DQ 오류", "system 오류" 로 분류.
- 재처리는 raw 를 재사용해야 하며, 사용자가 같은 파일을 다시 올리게 만들지 않는다.

---

## 6.6 위험 + 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| 공공 API 폐기/명세 변경 | pipeline 실패 | contract compatibility check + provider status dashboard |
| 서비스키/트래픽 제한 | 수집 지연 | rate limit + throttle + schedule 분산 |
| XML/비정형 응답 | mapping 실패 | adapter layer + sample based contract 생성 |
| 사용자 파일 품질 낮음 | DQ 실패 증가 | preview + DQ 추천 + 오류 sample |
| 개인정보 업로드 | 법/보안 리스크 | PII detection + masking + upload policy |
| 대용량 파일 업로드 | DB/worker 압박 | Object Storage 우선 + chunk parsing + async dry-run |
| mart 설계 오류 | 서비스 데이터 오염 | dry-run 기본 + publish approval + rollback plan |

---

## 6.6.1 Phase 5 → Phase 6 backlog 우선순위 (STEP 12 답변 Q3)

Phase 5 STEP 7 (5.2.4) 에서 *후순위* 로 미룬 8 종 ETL UX + STEP 11 의 backend-only
Performance Coach UI 를 다음 순서로 진행:

| 우선순위 | 항목 | 이유 |
|---|---|---|
| 1 | **Error Sample Viewer** | 실 외부 API/업로드 실증의 핵심 — *왜 실패했는가* 가 가장 자주 필요 |
| 2 | **Lineage View** | source → contract → mapping → mart → public API 흐름 시각화 |
| 3 | **Backfill Wizard** | 1년치 chunk + checkpoint 운영 (STEP 11 backend 완성, UI 만 남음) |
| 4 | **Source Wizard** | 새 도메인 추가의 12 단계 (`docs/onboarding/03_domain_playbook.md`) 를 인터랙티브 형태로 |
| 5 | **Publish Checklist 고도화** | Mini Checklist 5종 → lineage/load_perf/sample_review 추가 |
| 6 | **Node Preview** | 노드 1개의 입력/출력 sample 미리보기 |
| 7 | **Template Gallery** | 자주 쓰는 mapping / DQ rule 템플릿 |
| 8 | **SQL Performance Coach UI** | STEP 11 backend 의 verdict/warnings 시각화 |

각 항목은 Phase 6 의 별도 STEP. `docs/onboarding/03_domain_playbook.md` 의
playbook 12 단계를 wizard 가 따라가는 흐름.

---

## 6.7 Phase 6 종료 산출물

- 공공 OpenAPI 실증 파이프라인 1~2개.
- 사용자 업로드 샘플 페이지.
- Upload backend API.
- 실증용 domain/source contract/mapping/DQ/mart 정의.
- 1일 이상 polling 운영 로그.
- DQ 실패/재처리 walkthrough.
- 성능 baseline 리포트.
- 개인정보/업로드 보안 runbook.
- Phase 5 보정 backlog.
- ADR-0019 Field Validation 결과.

---

## 6.8 Phase 7 후보

Phase 6 결과에 따라 다음 중 하나를 선택한다.

- **Phase 7A — Multi-tenant / Organization**: 여러 조직이 각자 source/mart/DQ 를 관리.
- **Phase 7B — Public Data Product**: 검증된 mart 를 외부 API 상품으로 공개.
- **Phase 7C — AI-assisted Mapping/DQ**: 업로드 샘플을 보고 LLM 이 mapping/DQ 초안을 추천.
- **Phase 7D — CDC/Kafka PoC**: 실시간성이 검증된 도메인에 한해 Kafka/Debezium PoC.

