# KAMIS 도매시장 가격 — 코딩 0줄 데모 가이드

> **목적**: 새로 가입한 사용자가 *손으로 한 번도 코드를 짜지 않고* KAMIS OpenAPI →
> 표준화 → 마트 적재 파이프라인을 13분 안에 완성하는 시나리오.
>
> Phase 6 의 핵심 acceptance (`PHASE_6_PRODUCT_UX.md` § 6).

---

## 0. 사전 준비 (운영자/개발자 1회)

```bash
# 1. KAMIS API key 발급 — http://www.kamis.or.kr/customer/main/main.do
# 2. .env 또는 NCP Secret Manager 에 등록
KAMIS_CERT_KEY=발급받은_키

# 3. DB 마이그레이션 + agri_mart 테이블 생성
cd backend
alembic upgrade head           # 0048 까지 적용 → agri_mart.kamis_price 생성

# 4. (선택) 데모용 자산 자동 시드
python ../scripts/seed_kamis_vertical_slice.py
# → connector / contract / mapping / load_policy / dq_rule / workflow 한 번에 생성
```

> 시드 스크립트는 *멱등* 합니다. 같은 이름으로 두 번 실행해도 안전.

---

## 1. 사용자 시연 — 13분 시나리오

브라우저에서 `https://staging.<your-domain>` 로그인 후:

### Step 1 (2분) — Source/API Designer

1. 좌측 메뉴 **"Public API Connector"** 클릭
2. `+ 새 connector` 버튼 → 폼 입력:

| 필드 | 값 |
|---|---|
| 이름 | KAMIS 도매시장 일별가격 |
| 도메인 | `agri` |
| 리소스 코드 | `KAMIS_WHOLESALE_PRICE` |
| Endpoint URL | `http://www.kamis.or.kr/service/price/xml.do` |
| HTTP method | GET |
| Auth 방식 | query_param |
| Auth 파라미터 이름 | `p_cert_key` |
| Secret 참조 | `KAMIS_CERT_KEY` |
| Query 템플릿 | `{"action":"daily","p_product_cls_code":"01","p_regday":"{ymd}","p_returntype":"xml"}` |
| Response 형식 | XML |
| Response 추출 경로 | `$.response.body.items.item` |
| Timeout (sec) | 30 |
| 수집 주기 (cron) | `0 9 * * *` |

3. **"테스트 호출"** 버튼 → XML 응답 raw + 파싱된 rows preview 3건 확인 ✅
4. **"DRAFT 저장"** → `domain.public_api_connector` 1행 생성

### Step 2 (3분) — Mart Workbench

1. 좌측 메뉴 **"Mart Workbench"** 클릭
2. **Mart Schema** 탭에서 `+ 새 Mart 설계`:

```
도메인: agri
target_table: agri_mart.kamis_price
컬럼:
  ymd          TEXT          NOT NULL  PK
  item_code    TEXT          NOT NULL  PK
  item_name    TEXT          NOT NULL
  market_code  TEXT          NOT NULL  PK
  market_name  TEXT
  unit_price   NUMERIC
  unit_name    TEXT
  grade        TEXT
PARTITION BY: ymd
```

3. **"DDL 생성 + DRAFT 저장"** → `mart_design_draft` 1행. (이미 마이그레이션 0048
   로 만들어져 있으면 ALTER 또는 noop 표시)
4. **Load Policy** 탭으로 이동 → `+ 새 Load Policy`:
   - resource: `agri / KAMIS_WHOLESALE_PRICE`
   - mode: `upsert`
   - key_columns: `ymd, item_code, market_code`
   - chunk_size: 1000
5. 저장 → DRAFT.

### Step 3 (2분) — Field Mapping Designer

1. 좌측 메뉴 **"Field Mapping Designer"** 클릭
2. 도메인 = agri, contract 선택 (Step 1 connector 의 resource_code 와 매칭)
3. `+ 새 매핑 행` 8건 추가:

| source_path | target_table.column | transform |
|---|---|---|
| `$.regday` | `agri_mart.kamis_price.ymd` | `date.normalize_ymd` |
| `$.itemcode` | `.item_code` | — |
| `$.itemname` | `.item_name` | — |
| `$.marketcode` | `.market_code` | — |
| `$.marketname` | `.market_name` | — |
| `$.dpr1` | `.unit_price` | `number.parse_decimal` |
| `$.unit` | `.unit_name` | — |
| `$.kindname` | `.grade` | — |

4. 각 행 → DRAFT → REVIEW → APPROVED → PUBLISHED 전이.

### Step 4 (1분) — Quality Workbench

1. 좌측 메뉴 **"Quality Workbench"** → **DQ Rules** 탭
2. `+ 새 DQ Rule` 2건:
   - kind=`row_count_min`, severity=`ERROR`, rule_json=`{"min": 1}`
   - kind=`range`, severity=`WARN`, rule_json=`{"column":"unit_price","min":0,"max":10000000}`
3. PUBLISHED 까지 전이.

### Step 5 (3분) — ETL Canvas v2

1. 좌측 메뉴 **"ETL Canvas v2"** → workflow name 입력 (`kamis_daily`)
2. 좌측 palette 에서 박스 4개를 드래그하여 캔버스에 배치:
   - **PUBLIC_API_FETCH** → 우측 drawer 에서 connector 선택 (Step 1)
   - **MAP_FIELDS** → contract 선택 (Step 3)
   - **DQ_CHECK** → rule 선택 (Step 4)
   - **LOAD_TARGET** → load_policy 선택 (Step 2)
3. 박스 사이를 화살표로 연결 (마우스 hover 시 연결점 보임)
4. **저장** 버튼 → workflow_id 생성

### Step 6 (1분) — Dry-run

1. **"Dry-run"** 버튼 클릭 → `/v2/dryrun/workflow/{id}` 페이지로 이동
2. 자동 실행 → 4박스 모두 ✅ success 표시. row_count 12 (예시) 표시
3. 실 mart 변경은 0 (모든 트랜잭션 rollback)

### Step 7 (1분) — Publish

1. 캔버스 toolbar 의 **"PUBLISH"** 버튼 → workflow status DRAFT → PUBLISHED
2. cron `0 9 * * *` 활성화 → 매일 09:00 자동 실행 시작
3. (선택) `/v2/publish/load_policy/{policy_id}` 등 자산별 Mini Publish Checklist
   페이지에서 ADMIN 승인 → 자산 PUBLISHED

---

## 2. 검증 (실 적재 후 1일~1주)

```sql
-- 어제부터 적재된 row 확인
SELECT ymd, COUNT(*) AS rows
  FROM agri_mart.kamis_price
 WHERE ymd >= TO_CHAR(NOW() - INTERVAL '7 day', 'YYYYMMDD')
 GROUP BY ymd
 ORDER BY ymd DESC;

-- DQ 결과
SELECT result_id, run_id, rule_id, status, severity, sample_count
  FROM dq.quality_result
 WHERE rule_id IN (SELECT rule_id FROM domain.dq_rule
                    WHERE target_table = 'agri_mart.kamis_price')
 ORDER BY result_id DESC LIMIT 20;

-- 최근 dry-run 이력
GET /v2/dryrun/recent?kind=workflow
```

---

## 3. 문제 해결

| 증상 | 원인 / 조치 |
|---|---|
| 테스트 호출 401 | `KAMIS_CERT_KEY` 미등록 또는 API key 만료 |
| 테스트 호출 500 + xmltodict 에러 | 응답이 XML 가 아닌 HTML 오류 페이지. URL/params 재확인 |
| MAP_FIELDS dry-run 0 rows | source_table 미생성 — PUBLIC_API_FETCH 가 먼저 실행되어야 staging table 생성 |
| LOAD_TARGET 실패 — schema 거부 | `app_mart_write` 권한 누락. NCP staging 의 `agri_mart` schema GRANT 확인 |
| PUBLISH 버튼 disabled | workflow 가 아직 DRAFT 가 아닌 상태. 또는 자산이 모두 PUBLISHED 가 아님 |
| Canvas 박스 클릭 시 dropdown 비어있음 | Step 1~4 자산이 같은 도메인(agri)인지 확인. 도메인 mismatch 시 dropdown 미노출 |

---

## 4. 다음 단계 (Phase 7 backlog)

- 알림 연동 (`NOTIFY` 박스): DQ 실패 시 Slack 자동 발송
- Backfill: 과거 1년치 일자별 backfill (`/v2/backfill` API)
- Lineage Viewer: workflow → source/target 의존 그래프 시각화
- AI-assisted Mapping: 응답 sample 1개 입력 → mart 컬럼 자동 추천
