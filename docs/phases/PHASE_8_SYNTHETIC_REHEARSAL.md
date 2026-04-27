# Phase 8 — Synthetic Data Service Rehearsal (가상 시나리오 사전 리허설)

> **목적**: 실데이터 (실 유통사 API / OCR / 크롤링 / 소상공인 업로드) 확보 전에,
> *가상 시나리오 데이터로 플랫폼 전체를 미리 운영 연극처럼 리허설* 한다.
>
> 화면, 마트, 운영 흐름의 빈틈을 찾고 보완한 뒤 Phase 9 에서 실증 데이터로 진입.

작성일: 2026-04-26
선행 Phase: Phase 7 (공용 플랫폼 완성)

---

## 0. 한 문장

> **"실데이터 기다리지 말고, 시스템이 진짜 데이터를 받았을 때 어떻게 보일지 미리
> 시연하자"**

---

## 1. Phase 8 의 핵심 의문 (검증 질문)

| # | 검증 질문 |
|---|---|
| 1 | API 수집 데이터가 들어오면 화면에서 원천/정제/마트 데이터가 잘 보이는가? |
| 2 | 유통사별 상품명이 달라도 표준 품목으로 묶이는가? |
| 3 | 할인/행사/재고 변화가 서비스 화면에 자연스럽게 표현되는가? |
| 4 | OCR/크롤링/업로드 데이터도 API 데이터와 같은 마트에 합쳐지는가? |
| 5 | 오류, 누락, 이상값 발생 시 운영자가 어디서 문제를 확인하는가? |
| 6 | Canvas 프로세스가 15~20개 운영될 때 모니터링 화면이 충분한가? |

---

## 2. 4 가상 유통사 채널

각 유통사마다 *데이터 형식 + 의도적 문제* 를 다르게 둬서 전처리 자산이 정말로
공용 가능한지 검증한다.

| 가상 채널 | domain_code | 역할 | mart schema |
|---|---|---|---|
| **이마트** | `emart` | 대형마트 표준 API형 | `emart_mart` |
| **홈플러스** | `homeplus` | 행사/할인 정보가 풍부한 API형 | `homeplus_mart` |
| **롯데마트** | `lottemart` | 상품코드 체계가 다른 API형 | `lottemart_mart` |
| **하나로마트** | `hanaro` | 농축수산물 산지/등급/단위 정보가 많은 API형 | `hanaro_mart` |

**서비스 통합 마트**: `service_mart.product_price` — 4 유통사 데이터를 *동일 구조* 로 적재.

---

## 3. 유통사별 시나리오 + 의도적 오류

### 3.1 이마트 — 표준 API 성공 케이스
```
필드: retailer_product_code / product_name / price / discount_price / stock_qty
정상: EM-APL-001 / "당도선별 사과 1.5kg" / 12900 / 10900 / 42
문제 케이스:
  - retailer_product_code 누락 (DQ 실패)
  - stock_qty 음수 (DQ 실패)
  - 가격 0원 (range 실패)
```

### 3.2 홈플러스 — 행사/할인 케이스
```
필드: item_id / item_title / sale_price / promo_type / promo_start / promo_end
정상: HP-10031 / "국내산 양파 2kg" / 5980 / CARD_DISCOUNT / 2026-05-01 / 2026-05-07
문제 케이스:
  - promo_end < promo_start (역순 행사기간)
  - sale_price 만 있고 정상가 없음
  - promo_type 미정의 값
```

### 3.3 롯데마트 — 상품명 정규화 난이도 케이스
```
필드: goods_no / display_name / current_amt / unit_text
정상: LM-778812 / "[행사] GAP 인증 충주 사과 봉지 1.8kg" / 11900 / "봉"
문제 케이스:
  - 상품명에 마케팅 문구 다수: "오늘만 특가!"
  - 규격 추출 어려움: "한정수량"
  - confidence < 0.75 → 검수 큐
```

### 3.4 하나로마트 — 농축수산물 표준화 케이스
```
필드: product_cd / name / origin / grade / unit / price
정상: NH-AP-001 / "홍로 사과" / "충북 충주" / "특" / "10kg" / 48900
문제 케이스:
  - origin 자유 텍스트: "국내산", "수입(미국)"
  - grade 표준화: "특"/"상"/"1등급" 통일 필요
  - 단위 변환: kg / g / 봉 / 단 / 입
```

---

## 4. 공통 전처리 자산 카탈로그 (10종)

| 전처리 유형 | 설명 | 사용 유통사 |
|---|---|---|
| 필수값 검증 | 상품명/가격/수집일자 NULL 체크 | 모두 |
| 타입 정규화 | "12,900원" → 12900 | 홈플러스 |
| 이상값 제거 | 가격 0원 / 재고 음수 | 모두 |
| 상품명 클렌징 | "[행사]", "오늘만 특가" 제거 | 롯데마트 |
| 규격 추출 | "1.5kg" / "500g" / "30구" 분리 | 롯데마트, 하나로마트 |
| 단위 변환 | 100g당 가격 / kg당 가격 | 하나로마트 |
| 코드 표준화 | EM-APL-001 → FRT_APPLE | 모두 |
| 행사 표준화 | "1+1" → ONE_PLUS_ONE | 홈플러스 |
| 재고 상태화 | 0 → OUT_OF_STOCK | 모두 |
| 검수 분기 | confidence < 0.75 → 검수 큐 | 롯데마트 |

---

## 5. Canvas 프로세스 패턴 (4종)

```text
[이마트 표준 API]
  PUBLIC_API_FETCH → MAP_FIELDS → DQ_CHECK(필수+이상값) → STANDARDIZE(코드)
                  → LOAD_TARGET (emart_mart.price)
                  → LOAD_TARGET (service_mart.product_price)

[홈플러스 행사 API]
  PUBLIC_API_FETCH → MAP_FIELDS → DQ_CHECK(행사기간) → FUNCTION_TRANSFORM(행사표준화)
                  → STANDARDIZE → LOAD_TARGET → LOAD_TARGET (service_mart)

[롯데마트 상품명 정규화]
  PUBLIC_API_FETCH → MAP_FIELDS → FUNCTION_TRANSFORM(클렌징+규격추출)
                  → HTTP_TRANSFORM(LLM_CLASSIFY) → DQ_CHECK
                  → confidence<0.75 → DEDUP → 검수 큐 (분기)
                  → LOAD_TARGET → service_mart

[하나로마트 농축수산물]
  PUBLIC_API_FETCH → MAP_FIELDS → FUNCTION_TRANSFORM(산지/등급/단위)
                  → STANDARDIZE → LOAD_TARGET → service_mart
```

---

## 6. 8 Synthetic Scenarios (사용자 spec)

### 시나리오 1. 대형 유통사 API 4개 가격 수집
- 모두 다른 형식의 API → 같은 service_mart 로 모임
- 의도적 오류: 유통사 D 가격 누락 / 가격 문자열 / 비정형 상품명

### 시나리오 2. 행사/할인 가격 변경
- 정상가 + 행사가 + 행사기간 + 카드할인
- 의도적 오류: 행사 종료일 < 시작일, 행사가 > 정상가

### 시나리오 3. 재고 수시 변경
- 매장별 재고 snapshot
- 의도적 오류: 재고 음수, 마지막 확인 시각 너무 오래됨

### 시나리오 4. 외부 크롤링 업체 push
- `CRAWLER_RESULT_INGEST` 노드 사용
- 의도적 오류: 같은 URL 중복 push, 가격 300% 급등

### 시나리오 5. 외부 OCR 업체 push
- `OCR_RESULT_INGEST` 노드 사용
- 의도적 오류: confidence 0.62, 깨진 텍스트

### 시나리오 6. 소상공인 업로드
- `FILE_UPLOAD_INGEST` 노드 사용 (CSV/Excel)
- 의도적 오류: 컬럼명 불일치, 중복 업로드

### 시나리오 7. 외부 LLM API 전처리
- `HTTP_TRANSFORM` (provider_kind=LLM_CLASSIFY)
- 의도적 오류: timeout, schema 불일치, low confidence fallback

### 시나리오 8. 15~20개 동시 운영
- 모든 시나리오 + Operations Dashboard 모니터링
- 의도적 오류: 한 유통사 500, OCR timeout, DQ 폭증

---

## 7. 시연 흐름 (10 step)

```
1. 가상 유통사 API 4개 데이터 생성 (seed script)
2. 가상 크롤링/OCR/소상공인 업로드 데이터 생성
3. 각 채널별 Canvas 프로세스 실행
4. raw → mapping → DQ → standardize → mart 적재 확인
5. Service Mart 화면에서 가격/행사/재고 데이터 확인
6. 일부 오류 데이터 확인 (DQ 실패 / 검수 큐)
7. Operations Dashboard 에서 실패 노드 확인
8. 해당 노드 수정 후 dry-run
9. 운영 프로세스 재배포
10. 최종 마트 데이터 정상화 확인
```

---

## 8. 화면별 확인 항목

### 8.1 Operations Dashboard
| 항목 | 기대 |
|---|---|
| Workflows 카운트 | 4 (4 유통사) |
| Runs (24h) | 시드 후 4+ |
| Success Rate | 75~95% (의도적 오류 포함) |
| Pending Replay | 1~3 (실패 케이스) |
| Channels 목록 | emart_price / homeplus_promo / lottemart_canon / hanaro_agri |
| Heatmap | 노드별 success/failed 색상 표시 |

### 8.2 Service Mart Viewer (Phase 8 신설)
| 컬럼 | 기대 데이터 |
|---|---|
| 표준품목 | 사과 / 양파 / 대파 / 한우 / ... |
| 유통사 | 이마트 / 홈플러스 / 롯데마트 / 하나로마트 |
| 상품명 | 유통사별 다양 |
| 정상가 | 5000 ~ 50000 |
| 행사가 | 일부 |
| 재고 | 0 (품절) ~ 100 |
| 행사 | 카드할인 / 1+1 / 없음 |
| 상태 | 판매중 / 품절 |

### 8.3 Inbound Events
| 항목 | 기대 |
|---|---|
| audit.inbound_event 행 | 100+ (OCR/Crawler/Upload 시드 후) |
| status 분포 | RECEIVED → PROCESSING → DONE 흐름 |
| FAILED | 의도적 오류 케이스 |

---

## 9. 의도적 오류 매트릭스

| 오류 유형 | 시나리오 | 기대 동작 |
|---|---|---|
| 필수값 누락 | 1 / 6 | DQ 실패 (severity=ERROR) |
| 가격 이상값 | 1 / 4 | range DQ 실패 또는 anomaly |
| 잘못된 날짜 | 2 | promo_end < promo_start → DQ 실패 |
| 표준화 실패 | 3 (롯데마트) | confidence < 0.75 → 검수 큐 |
| 중복 수집 | 4 | idempotency_key UNIQUE → 409 |
| 재고 불일치 | 3 | DQ 실패 + 운영 alert |
| 외부 API 장애 | 7 | retry → fallback provider |
| 스키마 변경 | (Wave 7 backlog) | drift 감지 |

---

## 10. Phase 8 산출물

### 신규 migration
- `0051_synthetic_retailer_domains.py` — 4 유통사 도메인 + mart schema + service_mart

### 신규 seed scripts (Phase 8.4 정합성 정리)

실제 산출물은 **2개** 파일로 통합되어 있습니다 (구상한 3개 분리 파일 → 통합):

| 파일 | 역할 | 실행 시점 |
|---|---|---|
| `scripts/phase8_seed_synthetic_data.py` | **화면 확인용** — 4 유통사 mart 데이터 + service_mart 통합 (가격/할인/재고/검수 등 화면 노출 데이터) | `alembic upgrade head` 직후 |
| `scripts/phase8_seed_full_e2e.py` | **Canvas E2E 검증용** — 4 도메인 connector + mapping + load_policy + DQ + workflow + inbound channel 3종 + pipeline_run + node_run + crowd.task + 의도적 FAILED 케이스 | synthetic_data 다음 |

**실행 순서**:
```bash
# 1) 마이그레이션
cd backend && alembic upgrade head

# 2) 화면 확인용 mart 데이터
python scripts/phase8_seed_synthetic_data.py

# 3) Canvas E2E 자산 + run 이력
python scripts/phase8_seed_full_e2e.py

# 4) 검증
pytest backend/tests/integration/test_phase8_full_e2e.py
```

기존 문서가 언급한 `phase8_seed_retailers.py`, `phase8_seed_inbound_events.py` 는 작성되지
않았고, 동일 기능이 `phase8_seed_full_e2e.py` 안에 통합되어 있습니다 (사용자 § 5.6 보완 항목 #2).

### 신규 frontend
- `pages/v2/ServiceMartViewer.tsx` — 통합 service_mart 조회 화면
- `api/v2/service_mart.ts`

### 신규 backend
- `app/api/v2/service_mart.py` — 통합 mart 조회 endpoint

---

## 11. Phase 9 진입 체크리스트

Phase 8 종료 시 다음이 모두 확인되어야 Phase 9 (실증) 진입:

- [ ] Operations Dashboard 에서 4 채널 모두 보임
- [ ] Service Mart Viewer 에서 4 유통사 데이터 한 화면에 노출
- [ ] 의도적 오류가 *실제로* DQ/검수 큐로 분기됨
- [ ] dry-run 으로 사전 검증 → publish → 다시 실행 흐름 작동
- [ ] Inbound 채널 (OCR/Crawler/Upload) push → 자동 trigger 동작
- [ ] Operations Dashboard 의 dispatch 버튼으로 pending envelope 처리 가능
- [ ] 노드별 heatmap 으로 실패 노드 식별 가능
- [ ] 화면이 *실 운영* 처럼 보임 — 가상 데이터지만 실증적 느낌

---

## 12. 참조

- [PHASE_7_COMMON_PLATFORM.md](./PHASE_7_COMMON_PLATFORM.md)
- [ADR-0022](../adr/0022-inbound-push-receiver-standard.md)
- 사용자 *공용 데이터 수집 파이프라인 기반 농축수산물 가격 데이터 플랫폼 구상*
- 사용자 *4 유통사 + 8 시나리오* spec
