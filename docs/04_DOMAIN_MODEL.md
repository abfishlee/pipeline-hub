# 04. 도메인 모델 (농축산물 가격)

## 4.1 핵심 엔티티 (ERD 개요)

```
┌───────────────┐      ┌───────────────────┐      ┌───────────────┐
│ standard_code │◄─────│  product_master   │◄─────│ product_mapping│
│ (품목 표준)   │      │ (마스터 상품)     │      │ (유통사별 매핑)│
└───────────────┘      └────────┬──────────┘      └──────┬────────┘
                                │                         │
                                │                         │
                                ▼                         │
                         ┌────────────┐                   │
                         │ price_fact │                   │
                         │ (가격 이력) │                   │
                         └──────┬─────┘                   │
                                │                         │
                                ▼                         │
┌──────────────┐      ┌───────────────┐                   │
│  retailer    │◄─────│ seller_master │◄──────────────────┘
│  (유통사)    │      │ (매장/점포)   │
└──────────────┘      └───────────────┘
```

## 4.2 엔티티 정의

### 4.2.1 표준코드 (`mart.standard_code`)

- 농축산물 **품목 분류 표준.**
- 출처: 농림축산식품부 표준분류, aT KAMIS, 내부 보완 코드.
- 계층: `category_lv1` (채소/과일/축산/수산) → `lv2` → `lv3`.
- **표준코드 1개 = 품목 1개** (참외, 국내산 참외 이런 단위).
- 등급/포장/단위 같은 변형은 `product_master`에서 처리.

**business_key:** `std_code` (ex. `'FRT-CHAMOE'`)
**예시:**
```json
{
  "std_code": "FRT-CHAMOE",
  "category_lv1": "과일",
  "category_lv2": "박과",
  "item_name_ko": "참외",
  "aliases": ["참외", "Korean melon", "chamoe"],
  "default_unit": "1kg"
}
```

### 4.2.2 상품 마스터 (`mart.product_master`)

- 표준코드 + **등급 + 포장 + 단위 + 중량** 조합의 canonical 제품.
- 유통사별로 상품명이 달라도 마스터는 하나로 수렴한다.

**business_key:** `(std_code, grade, package_type, sale_unit_norm, weight_g)`
**예시:**
```
std_code=FRT-CHAMOE, grade='특', package='박스', sale_unit_norm='10kg', weight_g=10000
→ canonical_name='참외 특 10kg 박스'
```

### 4.2.3 유통사 (`mart.retailer_master`)

- 하나의 비즈니스 주체. 예: 이마트, 홈플러스, 쿠팡, 마켓컬리, aT농산물유통센터, 지역 로컬푸드 직매장.
- `retailer_type`: `MART / SSM / LOCAL / ONLINE / TRAD_MARKET / APP`

### 4.2.4 판매자 (`mart.seller_master`)

- **실제 가격이 관찰되는 단위.** 매장(오프라인 점포) 또는 온라인 스토어.
- `retailer_id`에 종속. 예: "이마트 용산점", "쿠팡 로켓프레시".
- 지역(시도/시군구) 정보 + geo point 포함 — 지역별 가격 통계의 근거.

### 4.2.5 가격 팩트 (`mart.price_fact`)

- **시간별로 관찰된 가격 1건 = 1 row.**
- `(product_id, seller_id, observed_at, price_krw)`가 한 기록.
- `unit_price_per_kg` 는 **정규화 단가**: `price / weight_g * 1000`.

## 4.3 business_key 규칙

| 엔티티 | business_key | 비고 |
|---|---|---|
| standard_code | `std_code` | 내부 관리 코드 |
| product_master | `(std_code, grade, package_type, sale_unit_norm, weight_g)` | 전체 조합 unique |
| retailer_master | `retailer_code` | 외부 코드면 쓰고, 없으면 `INT-<shortname>` |
| seller_master | `(retailer_id, seller_code)` | retailer 내 unique |
| product_mapping | `(retailer_id, retailer_product_code)` or `(retailer_id, raw_product_name_hash)` | 유통사가 코드 주면 전자 우선 |
| price_fact | 복합 — 사실상 append-only, dedup은 `(product_id, seller_id, observed_at, source_id)` |

## 4.4 표준화 파이프라인 (핵심 기능)

**원천 상품명 → product_mapping → product_master → standard_code** 로 이어지는 매핑이 플랫폼의 가치 제공 핵심이다.

### 4.4.1 표준화 단계

```
[1] 원천 상품명 수신
    "국산 참외 특품 10kg 박스 /이마트/20원/09:00"

[2] 정규화 (rule-based)
    - 공백/특수문자/괄호 정리
    - 중량/단위 추출: "10kg 박스", weight_g=10000, sale_unit='박스'
    - 등급 추출: "특품" → grade='특'
    - 산지 태그 제거 ('국산')

[3] 표준코드 매핑
    (3a) 규칙 사전에서 먼저 검색
         → aliases ['참외','chamoe'] 매칭 확인
    (3b) Trigram 유사도 조회
         SELECT std_code FROM mart.standard_code
         ORDER BY similarity(item_name_ko, '참외') DESC LIMIT 5;
    (3c) 임베딩 코사인 유사도 (HyperCLOVA X 또는 OpenAI)
         - precompute: 모든 std_code의 item_name_ko + aliases 임베딩
         - 원천 상품명 임베딩과 cosine 유사도 top-1 선택
    (3d) confidence 계산: 3a=1.0, 3b=trigram 점수, 3c=코사인 유사도
    (3e) 최종 confidence >= 0.9 → 자동 확정
         0.7~0.9 → crowd task 생성 (PRODUCT_MATCHING)
         < 0.7 → FAILED, 별도 검토

[4] product_master 조회/생성
    - (std_code, grade, package, unit_norm, weight_g)로 upsert
    - 신규면 canonical_name 자동 생성

[5] product_mapping upsert
    - (retailer_id, retailer_product_code) 또는 (retailer_id, raw_name)
    - match_method 기록

[6] stg.price_observation.std_code 업데이트
[7] price_fact insert
```

### 4.4.2 confidence 게이트

| confidence | 처리 |
|---|---|
| ≥ 0.95 | 즉시 Mart 반영 |
| 0.80 ~ 0.95 | 자동 반영 + 사후 샘플링 검수 (5%) |
| 0.70 ~ 0.80 | Crowd task 생성, 검수 후 반영 |
| < 0.70 | staging에만 보관, 주간 리포트 |

## 4.5 중복/매칭 규칙

### 4.5.1 가격 관찰 중복 (`price_fact`)

같은 `(product_id, seller_id, observed_at to minute)` + `price_krw` 는 중복 가격.
→ 수집 단계에서 `content_hash` 로 차단.

### 4.5.2 상품 매칭 충돌

같은 `(retailer_id, retailer_product_code)` 가 서로 다른 `product_id` 에 매핑되면 **CONFLICT**.
→ Crowd task (PRODUCT_MATCHING) 자동 생성.

### 4.5.3 유통사 매칭

외부 소스의 유통사명이 기존 `retailer_master` 에 없으면:
- 사업자번호 매칭 우선
- 없으면 이름 trigram 유사도 ≥ 0.9 시 제안
- 미확정이면 `UNMAPPED` 상태로 보관 후 관리자 확정

## 4.6 수집 경로별 도메인 매핑

| 수집 채널 | 원천 예시 | raw.object_type | stg 대상 | 특이사항 |
|---|---|---|---|---|
| 유통사 POS API | `{sku:"XXX", price:5000, store:"용산점", ts:...}` | JSON | price_observation | sku가 retailer_product_code |
| DB-to-DB | `products` 테이블 incremental | DB_ROW | price_observation | CDC 시 before/after 모두 저장 |
| 크롤링 (쿠팡/마컬) | HTML 상품 페이지 | HTML | price_observation | 파서 버전 필수 |
| 행사 전단 OCR | 마트 전단 이미지 | IMAGE | price_observation | OCR confidence + Crowd 검수 |
| 소비자 영수증 OCR | 영수증 사진 | RECEIPT_IMAGE | price_observation | 매장명/품목/가격 파싱, 개인정보 마스킹 필수 |
| aT KAMIS | 전통시장 일별 가격 | JSON/CSV | price_observation | 매장=시장 단위로 매핑 |
| 여기고기 앱 | 축산물 API | JSON | price_observation | 축산 한정 |

## 4.7 가격 통계 모델

**일별 집계 (`mart.price_daily_agg`)** 는 다음 기준으로 생성:
- `(agg_date, std_code, retailer_id, region_sido)` 그룹
- `min/avg/max/median/count` 계산
- 매일 00:30에 전일 재계산 (영수증 지연 수집 반영 위해 2일치 rolling).

**이상치 처리:**
- 동일 `std_code` 의 당일 median에서 ±5σ 이상 벗어나는 가격은 `dq.quality_result` 에 기록하고 집계에서 제외.
- 수집 당일 price=0 또는 null은 수집 단계에서 제거.

## 4.8 단위 정규화

**중량 정규화:**
- 모든 중량은 `weight_g` 로 저장 (gram).
- 입력: "1kg"/"500g"/"1박스(5kg)" → 파싱 후 `weight_g`.
- 박스 등 multi-pack은 box 내 총 중량 저장.

**판매 단위 정규화:**
- `sale_unit_norm` 값은 표준 라벨만:
  `kg | g | 개 | 봉 | 박스 | 묶음 | L | ml`

**가격 정규화:**
- `price_krw`: 원 단위 정수형도 괜찮지만 NUMERIC(14,2) 유지 (할인 계산 때문).
- `unit_price_per_kg`: kg 기준 단가. weight_g가 없으면 NULL.

## 4.9 상품 표준코드 초기 시드 전략

Phase 2 시작 시점에 다음을 시드로 적재:

1. **농림축산식품부 식품표준 분류** (공공데이터포털 CSV) — 대분류/중분류/소분류.
2. **aT KAMIS 품목 코드** — 도매/소매 가격 조사 품목.
3. **자체 보완 코드** — 위 두 출처에 없지만 시장에서 흔한 품목 (예: 로컬 브랜드, 수입 특용품).

시드 스크립트: `scripts/seed_standard_codes.py`

## 4.10 도메인 용어집

| 용어 | 영어 | 정의 |
|---|---|---|
| 표준코드 | standard code | `mart.standard_code.std_code` |
| 마스터 상품 | product master | 품목 × 등급 × 포장 × 단위의 canonical 결합 |
| 관측 | observation | 시점별 가격 1건 |
| 표준화 | standardization | 원천 상품명 → 표준코드 매핑 전 과정 |
| 매핑 | mapping | 특정 유통사의 상품명 → 상품 마스터 연결 |
| 유통사 | retailer | 이마트 등 비즈니스 주체 |
| 판매자 | seller | 유통사 산하 실제 판매 지점 |
| 팩트 | fact | 이력성 append-only 테이블 (price_fact 등) |
| 크라우드 | crowd | 내부 직원 검수 작업 |
| 승인자 | approver | SQL/Mart 변경 승인 권한 보유자 |
| 표준화 confidence | std_confidence | 0.0~1.0, 자동/수동 결정 임계치에 사용 |

## 4.11 샘플 질의 (API 제공용)

```sql
-- 참외 최근 7일 유통사별 평균가
SELECT pda.retailer_id, r.retailer_name, pda.agg_date, pda.avg_price_krw
FROM mart.price_daily_agg pda
JOIN mart.retailer_master r ON r.retailer_id = pda.retailer_id
WHERE pda.std_code = 'FRT-CHAMOE'
  AND pda.agg_date >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY pda.agg_date, pda.avg_price_krw;

-- 특정 매장의 오늘 가격
SELECT pm.canonical_name, pf.price_krw, pf.observed_at
FROM mart.price_fact pf
JOIN mart.product_master pm ON pm.product_id = pf.product_id
WHERE pf.seller_id = $1
  AND pf.observed_at::date = CURRENT_DATE
ORDER BY pf.observed_at DESC;

-- 서울 시내 '돼지고기 앞다리살' 가격 분포
SELECT sm.region_sigungu, AVG(pf.unit_price_per_kg) AS avg_per_kg
FROM mart.price_fact pf
JOIN mart.seller_master sm ON sm.seller_id = pf.seller_id
JOIN mart.product_master pm ON pm.product_id = pf.product_id
WHERE pm.std_code = 'LVS-PORK-FRONTLEG'
  AND sm.region_sido = '서울'
  AND pf.observed_at >= now() - INTERVAL '1 day'
GROUP BY sm.region_sigungu;
```
