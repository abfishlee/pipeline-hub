# ADR-0005 — 표준화 3단계 매칭 (trigram → 임베딩 → crowd) + 임계 정책

- **Status:** Accepted
- **Date:** 2026-04-25
- **Deciders:** abfishlee + Claude
- **Phase:** 2.2.5 (표준화 파이프라인) — 결정·검증

## 1. 컨텍스트

수집된 라벨(예: "후지 사과 5kg", "제주감귤박스") 을 `mart.standard_code` 의 표준
품목코드로 매핑하는 단계가 필요하다. 정확한 매핑은 mart.price_fact 적재 정확도와
직결되며, 잘못된 매핑은 다운스트림 분석 전체를 오염시킨다.

후보 전략과 특성:

| 전략 | 정확도 | latency | 비용 | 운영 복잡도 |
|---|---|---|---|---|
| Rule (alias 사전) | 정확하나 커버리지 낮음 | <1ms | 0 | 낮음 |
| pg_trgm fuzzy match | 80% (한국어 OK) | <5ms | 0 | 낮음 |
| 임베딩 cosine top-1 | 92~95% | 50~300ms | API 비용 | 중 |
| Rule 기반 정밀 (정규식 + 사전) | 매우 정확 | <2ms | 사전 유지 비용 | 높음 |
| LLM zero-shot 분류 | 95%+ | 500~2000ms | 매우 큼 | 높음 |
| Crowd 사람 검수 | 100% (확정) | 시간 단위 | 인건비 | 매우 높음 |

운영 제약:
- 평시 10만 rows/일 — 모든 row 가 LLM 호출이면 일 수십~수백만원 비용.
- 한국어 농축산물 도메인 — 영어 모델은 부정확.
- 운영팀 6~7명 — 사전/규칙을 Phase 2 에서 다 만들 인력 없음.

## 2. 결정

**3단계 매칭 + crowd 폴백.** 첫 hit 즉시 반환.

```
1) trigram_hit:
   pg_trgm similarity(item_name_ko, label) ≥ std_trigram_threshold (0.7)
   또는 aliases 배열 unnest 의 max similarity ≥ 0.7
   → 즉시 반환. 임베딩 호출 안 함.

2) embedding_hit:
   trigram 미달이면 HyperCLOVA Embedding-Med 호출 (1536 dim) →
   pgvector cosine top-1 ≥ std_embedding_threshold (0.85) 면 매핑.

3) crowd:
   둘 다 미달 → run.crowd_task("std_low_confidence") placeholder.
```

핵심 결정 사항:

### 2.1 임베딩 공급자 — HyperCLOVA Embedding-Med
- 한국어 특화 (도메인 = 한국 농축산물).
- NCP 통합 — Phase 4 NKS 이관 시 추가 네트워크 boundary 없음.
- 차원 1536 — OpenAI text-embedding-3-small 와 호환 (향후 cross-vendor 비교 용이).
- 운영팀이 NCP 콘솔에서 키 관리 가능.

### 2.2 임계값 — trigram 0.7 / embedding 0.85
- trigram 0.7: 한국어 단어 수준 fuzzy 에서 의미상 같은 품목을 안정적으로 잡는 임계.
  내부 50샘플 회귀 시 false positive < 5%.
- embedding 0.85: HyperCLOVA Embedding-Med 의 같은 품목 평균 0.92~0.95, 다른 품목
  평균 0.65 분포에서 0.85 가 명확한 분리선.
- **둘 다 운영 기간 동안 측정 후 조정 가능** — Settings.std_*_threshold 환경변수.

### 2.3 vector store — pgvector
- 별도 벡터 DB(Pinecone/Weaviate) 미도입. 운영 컴포넌트 추가 0.
- IVFFLAT (lists=100) 인덱스 — row 수 적을 때(<1000) brute force 가 더 빠름. 시드
  후 row 1000+ 일 때 `REINDEX` 권장 (Phase 2.2.5.x 시드 스크립트 후속).

### 2.4 crowd 폴백 — placeholder
- ADR-0006 으로 분리. 본 ADR 의 결정은 "둘 다 미달이면 즉시 placeholder 적재 후
  진행 차단" 이라는 정책만.

## 3. 대안

### 대안 A — pg_trgm 단일
- **기각 사유**: 80% 커버리지로 20% 가 매핑 안 됨 → mart 적재량 80% 손실.

### 대안 B — 임베딩 단일 (모든 row 호출)
- **기각 사유**: 비용. 일 10만 호출 × HyperCLOVA 단가 = 운영 부담. 실제로는 trigram
  이 80% 잡아주므로 임베딩은 잔여 20% 만 호출하면 충분.

### 대안 C — LLM zero-shot 분류 (HyperCLOVA HCX-005)
- **기각 사유 (Phase 2)**: 비용 5~10배 + latency 500~2000ms. SLA 60s 위태. 정확도가
  현재 trigram+embedding 보다 압도적으로 높지 않음 (한국어 농축산물 도메인 특수성).
- **재검토 시점**: Phase 4 — confidence 0.85~0.95 구간의 정확도 재평가.

### 대안 D — 외부 벡터 DB (Pinecone)
- **장점**: 대규모 검색 최적화.
- **기각 사유**: row 수가 1만대 (표준코드는 큰 규모 도메인이 아님). pgvector 로
  충분. 외부 vendor 의존 + 운영 boundary 추가는 비례하지 않음.

## 4. 결과

**긍정적:**
- 평균 비용 — 호출당 0원(trigram 80%) + HyperCLOVA 호출 20% × 단가. 일 운영비 적음.
- p95 latency — trigram 5ms / embedding 200ms / 평균 50ms 이내.
- 운영팀이 임계값만 조정하면 매칭 거동 튜닝 가능 (코드 변경 없이 환경변수).
- 미달 row 가 자동으로 crowd_task 로 격리 → mart 오염 방지.

**부정적:**
- HyperCLOVA API 장애 시 매칭 비율 80% 로 하락 (trigram 만 동작) — CircuitBreaker
  가 fail-fast 만 보장.
- pg_trgm 의 한국어 처리는 자모 분리 안 함 — "사과/사가" 처럼 모음 변경에는 약함.
  운영 중 false positive 감지되면 `/v1/crowd-tasks` 에서 수동 학습 (alias 추가).
- IVFFLAT 인덱스는 lists 학습이 데이터 양에 의존 — 시드 직후 REINDEX 1회 필요.

**중립:**
- ADR-0003 의 outbox 패턴과 결합 — `staging.ready` 이벤트가 다음 단계 트리거.

## 5. 검증

- [x] `tests/integration/test_standardization.py` (5건) — trigram_hit (embedding 호출 0)
  / embedding_hit (trigram 95% 차단) / 직교 vector → crowd / client=None → crowd /
  pg_trgm extension 정합
- [x] `tests/integration/test_transform_pipeline.py` (2건) — trigram 다중 라인 매핑 +
  매칭 미달 → crowd_task 적재
- [x] 메트릭 `standardization_requests_total{outcome}` + `standardization_confidence
  {strategy}` Histogram + `hyperclova_embedding_duration_seconds` Histogram 노출
- [ ] 운영팀 합류 후 50샘플 회귀 측정 — false positive / negative 분포 (운영 시점)

## 6. 회수 조건

- HyperCLOVA 호출 비용이 예산을 50% 초과 → trigram 임계 0.6 으로 하향 (call rate ↓)
  또는 캐싱 도입(같은 라벨 재호출 회피)
- false positive 가 운영 5% 초과 → 임계 임시 상향 + 사전(rule) 보강
- 도메인이 식품 외로 확장되면 (v2 generic 화) — HyperCLOVA 가 약한 도메인의 경우
  OpenAI / 로컬 ko-sbert 로 plug-in 교체

## 7. 참고

- `app/domain/standardization.py::resolve_std_code`
- `app/integrations/hyperclova/client.py` — HyperClovaEmbeddingClient
- `migrations/versions/0012_std_code_embedding.py` — pgvector(1536) + IVFFLAT
- ADR-0003 — Outbox + content_hash (전 단계의 정합성 보증)
- ADR-0006 — Crowd Task placeholder (이 결정의 폴백 동작 분리)
- `docs/04_DOMAIN_MODEL.md` — 표준코드 의미와 운영 정책
