# Phase 8.1 — Synthetic Rehearsal Hardening (보완 실행 계획서)

> 작성일: 2026-04-27
> 선행: Phase 8 가상 데이터 시드 완료 (commit `478b7bb`)
> 목적: 사용자 분석에 따른 5가지 빈틈 보완 + 8개 UX 개선

---

## 0. 사용자 분석 요약 (입력)

### 시스템 완성도 매트릭스
| 영역 | 완성도 | 판단 |
|---|---|---|
| 공통 수집 채널 구조 | 80% | API/Webhook/Upload/OCR/Crawler/DB 노드 코드 존재 |
| v2 Canvas/노드 기반 설계 | 70% | 노드 카탈로그 확장됨, 전체 실행 검증 더 필요 |
| Inbound 외부 Push 수집 | 65% | HMAC 구현, API Key/mTLS 미구현 |
| Phase 8 가상 실증 데이터 | 80% | 4 유통사 시나리오 + seed 존재 |
| 서비스 마트 화면 | 80% | API + 화면 구현 존재 |
| 운영 모니터링 | 65% | 대시보드 있으나 일부 placeholder |
| 테스트/운영 검증 | 45% | frontend build OK, backend pytest 미실행 |

### 5가지 최우선 보완 (사용자 지정)
1. **백엔드 테스트 환경 복구** (`No module named pytest`)
2. **Phase 8 E2E 테스트 추가** (alembic→seed→service_mart→inbound→workflow 일괄)
3. **Inbound 자동화 완성** (수동 dispatch 제거)
4. **운영 dashboard 지표 보강** (rows_24h placeholder → 실값)
5. **CDC_EVENT_FETCH 정리** (등록 또는 backlog 명확)

### 8가지 UX 개선 (사용자 지정)
1. **ETL Canvas** — 진행 바 + 자산 누락 경고 + 템플릿
2. **NodeConfigPanelV2** — 노드별 전용 폼 + raw JSON 접기 + 자산 상태
3. **Source / API Connector** — URL 자동 감지 + 인증 탭
4. **Field Mapping Designer** — 시각 매핑 (JSON tree drag&drop)
5. **Mart Workbench** — 간단/전문가 모드 + 템플릿
6. **Quality Workbench** — DQ rule 추천 세트 + 실패 sample
7. **Operations Dashboard** — 실패 우선 정렬 + 원인 분류
8. **Service Mart Viewer** — 최저가/평균가 비교 + lineage

---

## 1. Phase 8.1 의 한 문장

> **"기능은 충분 — 화면 흐름과 자동화의 빈틈을 보완해서 *진짜로 운영하는 시스템*
> 으로 만든다"**

---

## 2. 우선순위 + 일정

본 Phase 는 사용자가 *자고 일어났을 때 바로 확인 가능*하도록 즉시 실행한다.
Sprint 1회 (1세션) 안에 5+3 = 8개 항목 처리.

| 우선순위 | 작업 | 분량 | 효과 |
|---|---|---|---|
| 🔴 P0 | 백엔드 pytest 환경 복구 + E2E 테스트 | 30분 | 회귀 검증 |
| 🔴 P0 | Inbound 자동화 (Dramatiq actor 또는 background poll) | 30분 | 시나리오 4/5/6 자동화 |
| 🟠 P1 | Operations Dashboard placeholder 수정 | 20분 | 모니터링 정확성 |
| 🟠 P1 | CDC_EVENT_FETCH stub 등록 | 10분 | 노드 카탈로그 일관성 |
| 🟡 P2 | Service Mart Viewer 강화 (최저가/평균가) | 30분 | 시연 임팩트 |
| 🟡 P2 | NodeConfigPanelV2 자산 상태 + raw JSON 접기 | 20분 | UX |
| 🟡 P2 | ETL Canvas 진행바 + 자산 누락 경고 | 20분 | UX |
| 🟢 P3 | Source/API/Mapping/Mart/Quality 추천·템플릿 | (Phase 9 이월 — 시각 매핑 등 큰 작업) | UX |

P0~P2 만 본 Sprint 에서 처리. P3 (시각 매핑 / 간단모드 / 추천세트) 는 Phase 9 진입 후 별도 PR.

---

## 3. P0 — 백엔드 테스트 환경 복구 + E2E

### 3.1 pytest 설치
backend `pyproject.toml` 의 dev dependency 그룹에 pytest 가 이미 정의됨. uv 로 sync:
```bash
cd backend
uv sync --dev   # 또는 .venv/Scripts/pip install pytest pytest-asyncio
```

확인: `.venv/Scripts/pytest.exe --version`.

### 3.2 Phase 8 E2E 테스트 추가
신규 `backend/tests/integration/test_phase8_full_e2e.py`:

```python
def test_phase8_full_pipeline(it_client, admin_auth):
    """alembic → seed → API 조회 → inbound 수신 → dispatch → workflow 실행 검증."""

    # 1. 4 유통사 connector 등록 확인
    res = it_client.get("/v2/connectors/public-api", headers=admin_auth)
    assert res.status_code == 200
    connectors = res.json()
    retailer_codes = {c["domain_code"] for c in connectors}
    assert {"emart", "homeplus", "lottemart", "hanaro"}.issubset(retailer_codes)

    # 2. 4 유통사 service_mart 통합 확인
    res = it_client.get("/v2/service-mart/channel-stats", headers=admin_auth)
    stats = res.json()
    retailers_in_mart = {s["retailer_code"] for s in stats}
    assert {"emart", "homeplus", "lottemart", "hanaro"}.issubset(retailers_in_mart)

    # 3. 5 workflow + 28 runs 확인
    res = it_client.get("/v2/operations/channels", headers=admin_auth)
    channels = res.json()
    assert len(channels) >= 5

    # 4. inbound channel push → dispatch → workflow trigger
    # (HMAC 시뮬레이션 + dispatch)

    # 5. operations summary 의 실값 확인
    res = it_client.get("/v2/operations/summary", headers=admin_auth)
    summary = res.json()
    assert summary["workflow_count"] >= 4
```

---

## 4. P0 — Inbound 자동화

### 4.1 현재 한계
- `POST /v1/inbound/{channel_code}` 는 RECEIVED 상태로 envelope 만 저장
- workflow trigger 는 `POST /v2/operations/dispatch-pending` 수동 호출 필요

### 4.2 자동화 — Background poller (간단 버전)
Dramatiq actor cron 통합은 추후 보강. 1차는 backend 의 `lifespan` 안에서 background
asyncio task 로 5초마다 dispatch_received_envelopes 호출.

```python
# backend/app/workers/inbound_dispatcher.py (신규)
async def inbound_dispatcher_loop(stop_event):
    while not stop_event.is_set():
        try:
            sm = get_sync_sessionmaker()
            with sm() as s:
                results = dispatch_received_envelopes(s, limit=20)
                if results:
                    log.info("inbound_dispatch", count=len(results))
                s.commit()
        except Exception as exc:
            log.warning("inbound_dispatch_failed", exc_info=exc)
        await asyncio.sleep(5)
```

`main.py` lifespan 에서 task 시작 + SIGTERM 시 stop_event 설정.

### 4.3 검증
- channel.workflow_id 가 binding 된 채널로 push → 5초 내 status=PROCESSING + workflow_run_id 채워짐

---

## 5. P1 — Operations Dashboard 보강

### 5.1 rows_24h 실값 연결
현재 `/v2/operations/channels` 의 `rows_24h` 가 항상 0. node_run.output_json
의 row_count 를 합산.

```sql
-- channels 응답에 추가
SELECT pr.workflow_id,
       SUM(COALESCE((nr.output_json->>'row_count')::int, 0)) AS rows_24h
  FROM run.pipeline_run pr
  JOIN run.node_run nr USING (pipeline_run_id, run_date)
 WHERE pr.started_at >= now() - INTERVAL '24 hour'
   AND nr.node_type IN ('LOAD_TARGET', 'LOAD_MASTER')
 GROUP BY pr.workflow_id
```

### 5.2 실패 원인 분류
새 endpoint `/v2/operations/failure-summary`:
- node_type 별 실패 분류 (DQ_CHECK / LOAD_TARGET / PUBLIC_API_FETCH 등)
- 최근 24시간 실패 5건 샘플

dashboard 화면에 "FAILED CATEGORIES" 카드 추가.

---

## 6. P1 — CDC_EVENT_FETCH

### 6.1 stub 등록
node_type 에 등록되어 있지만 dispatcher 미연결. Wave 1B 에서 placeholder 등록만:

```python
# nodes_v2/cdc_event_fetch.py (신규 stub)
def run(context, config):
    return NodeV2Output(
        status="success",
        row_count=0,
        payload={
            "note": "Phase 8.1 stub — full impl is Phase 9 backlog",
            "channel_code": config.get("channel_code"),
        },
    )
```

dispatcher 등록.

---

## 7. P2 — Service Mart Viewer 강화

### 7.1 최저가/평균가 비교 (표준품목 선택 시)
선택된 std_product 의 4 유통사 가격 비교:
- 정상가 / 행사가 / 최저가 (행사 적용 시) / 평균가
- 막대 그래프 또는 표에서 색상 강조

### 7.2 가격 변동 차트 (lineage 기초)
`service_mart.product_price` 의 collected_at 기준 7일 추이:
- recharts LineChart (기존 dependency)
- std_product_code + retailer_code 별로 line

---

## 8. P2 — NodeConfigPanelV2 보완

### 8.1 자산 상태 표시
각 자산 dropdown 의 옆에 status 뱃지 (DRAFT/REVIEW/APPROVED/PUBLISHED).

### 8.2 raw JSON 접기
`<details>` 로 감싸 기본 닫힘. "고급 설정" 라벨.

---

## 9. P2 — ETL Canvas 진행바

### 9.1 진행 바
캔버스 상단에 6단계 progress bar:
```
1.수집 → 2.매핑 → 3.정제·표준화 → 4.DQ → 5.마트 적재 → 6.검증·배포
```
캔버스 안에 해당 노드 종류가 있으면 색 채우기.

### 9.2 자산 누락 경고
박스 클릭 시 자산이 비었으면 빨간 점 + 토스트.

---

## 10. P3 (Phase 9 이월)

다음은 본 Sprint 에서 *제외* (분량 큼):
- Field Mapping 시각 매핑 (JSON tree + drag&drop) — 별도 라이브러리 필요
- Mart Workbench 간단/전문가 모드 + 템플릿 — 정식 wizard 디자인 필요
- Quality Workbench DQ rule 추천 세트 — 추천 엔진 설계 필요
- Source/API Connector URL 붙여넣기 자동 감지 — 별도 OpenAPI introspection
- Master Merge / 가격 변동 lineage 의 풀 시각화

---

## 11. 산출물

### 신규 파일
- `backend/tests/integration/test_phase8_full_e2e.py`
- `backend/app/workers/inbound_dispatcher.py`
- `backend/app/domain/nodes_v2/cdc_event_fetch.py` (stub)
- `frontend/src/components/canvas/CanvasProgressBar.tsx`
- `frontend/src/components/dashboard/FailureCategoriesCard.tsx`
- `frontend/src/components/service_mart/PriceCompareCard.tsx`

### 수정 파일
- `backend/app/api/v2/operations.py` — rows_24h 실값 + failure-summary
- `backend/app/main.py` — lifespan inbound_dispatcher_loop 시작
- `backend/app/domain/nodes_v2/__init__.py` — CDC stub 등록
- `frontend/src/components/designer/NodeConfigPanelV2.tsx` — 상태 뱃지 + JSON 접기
- `frontend/src/pages/v2/EtlCanvasV2.tsx` — 진행바
- `frontend/src/pages/v2/ServiceMartViewer.tsx` — 가격 비교 + 차트

---

## 12. acceptance — 본 Sprint 종료 시점

- [ ] backend pytest 통과 — 회귀 (KAMIS) + 신규 Phase 8 E2E
- [ ] inbound 채널 push → 5초 내 자동 workflow trigger 확인
- [ ] Operations Dashboard 의 rows_24h 가 실값 (0 아님) + 실패 원인 분류 표시
- [ ] CDC_EVENT_FETCH 노드 dispatcher 등록 (stub OK)
- [ ] Service Mart Viewer 의 std_product 선택 시 4 유통사 가격 비교 표 노출
- [ ] NodeConfigPanelV2 의 자산 dropdown 옆 상태 뱃지 + 고급설정 접힘
- [ ] ETL Canvas 진행바 6단계 표시 + 자산 누락 시 경고

---

## 13. 다음 Phase

**Phase 9 — 실증 진입** (실 KAMIS / 4 유통사 API key 발급) 또는 **Phase 8.2 — UX
시각 매핑** (P3 항목 처리) 중 사용자가 선택.
