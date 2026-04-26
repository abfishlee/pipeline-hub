# Phase 8.2 — Deep UX Sprint (비개발자 사용성 보완)

> 작성일: 2026-04-27
> 선행: Phase 8.1 commit `1ad3d61`
> 목적: Phase 8.1 에서 P3 로 이월된 *깊은 UX* 항목을 본 sprint 에서 처리하여
> "공용 플랫폼 제품" 시연 임팩트 확보

---

## 0. Phase 8.1 적용도 결과 (입력)

사용자 요구 26개 세부 항목 중:
- ✅ 5개 (19%) — Canvas 진행바, JSON 접기, 가격 비교, 실패 우선 정렬, 실패 분류
- 🟡 2개 (8%) — Run detail 링크, 유통사 필터
- ❌ 19개 (73%) — 미구현

본 Phase 에서 19개 미구현 항목을 가능한 한 모두 처리.

---

## 1. 작업 범위 (8 영역 × 2~5 항목)

| 우선순위 | 영역 | 작업 | 영향 |
|---|---|---|---|
| 🔴 P0 | Mart Workbench | 4 마트 템플릿 (price fact / master / stock / promo) | 진입장벽 ↓↓ |
| 🔴 P0 | Quality Workbench | DQ rule 추천 세트 (3 카테고리 × 3 템플릿) | 진입장벽 ↓↓ |
| 🟠 P1 | NodeConfigPanelV2 | 자산 상태 뱃지 + 잘못된 조합 차단 | 운영 안전성 |
| 🟠 P1 | ETL Canvas | 자산 누락 경고 + 실행 준비 체크리스트 | 운영 안전성 |
| 🟠 P1 | Source/API Connector | URL 붙여넣기 → 파라미터 자동 감지 | 진입장벽 ↓ |
| 🟡 P2 | Field Mapping Designer | 시각 매핑 (좌 JSON tree + 우 컬럼 + 단순 picker) | 비개발자 사용성 |
| 🟡 P2 | Service Mart Viewer | 가격 추이 차트 (Recharts) + lineage 링크 | 시연 임팩트 |
| 🟡 P2 | Operations Dashboard | 재실행 버튼 + 24h 추이 차트 | 운영 편의 |

---

## 2. 작업 별 spec

### 2.1 Mart 템플릿 4종 (Mart Workbench)
"+ 새 Mart 설계" 다이얼로그 좌측에 템플릿 사이드바 추가:
- 가격 fact (`price_fact`) — ymd / item_code / market_code / unit_price / observed_at
- 상품 마스터 (`product_master`) — product_code / name / category / std_code / brand
- 재고 snapshot (`stock_snapshot`) — store_code / product_code / stock_qty / observed_at
- 행사 fact (`promo_fact`) — promo_code / product_code / start / end / promo_type / discount_rate

각 템플릿 클릭 시 폼이 자동 채워짐.

### 2.2 DQ rule 추천 세트
"+ 새 DQ Rule" 좌측에 카테고리:
- **필수값** — 가격 NULL / 상품코드 NULL / 수집일 NULL
- **이상값** — 가격 음수, 가격 0, 재고 음수
- **기간 검증** — promo_end < promo_start, 미래 날짜
- **중복 검증** — 상품코드 + 매장 unique

각 추천 시 rule_kind / rule_json 자동 채움.

### 2.3 자산 상태 뱃지 (NodeConfigPanelV2)
각 자산 dropdown 의 옆에 status 뱃지. dropdown option 에 `[DRAFT]` / `[PUBLISHED]` 표기. PUBLISHED 가 아닌 자산은 빨간 경고.

### 2.4 잘못된 조합 차단
PUBLISHED workflow 가 DRAFT 자산을 참조하면 *PUBLISH 차단* + UI 경고.

### 2.5 Canvas 자산 누락 경고
캔버스 우측 상단 또는 하단에 *실행 준비 체크리스트*:
- ✅ 모든 박스에 자산 dropdown 선택됨
- ✅ 모든 노드 화살표 연결됨
- ✅ start/end 박스 존재
- ⚠ source 박스 없음 / load 박스 없음 등

### 2.6 Source/API URL 자동 감지
endpoint_url 입력 시 query string 부분이 자동으로 query_template 으로 옮겨짐:
- 입력: `https://api.example.com/v1/products?category=fruit&limit=100`
- 자동: endpoint_url=`https://api.example.com/v1/products`, query_template=`{"category": "fruit", "limit": "100"}`

### 2.7 Field Mapping 시각 매핑 (단순 picker — 진정한 drag&drop 은 Phase 9)
- 좌측: contract 의 sample 응답 JSON 을 tree 로 표시 (각 노드 클릭 시 source_path 자동 입력)
- 우측: target table 컬럼 목록 (이미 있음, useTableColumns 활용)
- 매핑 추가 시 sample 의 type 과 target type 비교 → 불일치면 경고

### 2.8 Service Mart 차트
선택된 std_product 의 7일 가격 추이 — recharts LineChart, 4 유통사 line.

### 2.9 Operations Dashboard 재실행 + 추이
- 24h 시간별 success/failed 막대 차트 (recharts BarChart)
- 실패 채널의 "재실행" 버튼 (PipelineRun trigger)

---

## 3. 산출물

### 신규 파일
- `frontend/src/components/mart/MartTemplates.tsx`
- `frontend/src/components/quality/DqRuleTemplates.tsx`
- `frontend/src/components/canvas/CanvasReadinessChecklist.tsx`
- `frontend/src/components/source/UrlAutoParser.tsx` (or in-page hook)
- `frontend/src/components/mapping/JsonTreePicker.tsx`
- `frontend/src/components/service_mart/PriceTrendChart.tsx`
- `frontend/src/components/dashboard/HourlyTrendChart.tsx`

### 수정 파일
- `MartDesigner.tsx`, `QualityWorkbench.tsx`, `NodeConfigPanelV2.tsx`,
  `EtlCanvasV2.tsx`, `SourceApiDesigner.tsx`, `FieldMappingDesigner.tsx`,
  `ServiceMartViewer.tsx`, `OperationsDashboard.tsx`

---

## 4. 검증

- 모든 frontend build 통과
- 14/14 회귀 테스트 통과
- 사용자가 자고 일어나서 화면 직접 확인 가능
