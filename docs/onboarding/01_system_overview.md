# 1. 시스템 개요

## 한 문장
> *"농축산물 가격 데이터 수집·표준화 플랫폼"이 Phase 5 에서 **공용 데이터 수집
> 운영체제** 로 일반화되었다. 새 도메인은 yaml + migration + seed 만으로 추가."*

## v1 ↔ v2 (Strangler Pattern)

| 구분 | v1 | v2 |
|---|---|---|
| 라우트 prefix | `/v1/*`, `/public/v1/*` | `/v2/*`, `/public/v2/{domain}/*` |
| 도메인 인지 | 농축산물 한정 | yaml registry → domain 별 schema |
| ORM | SQLAlchemy ORM 정적 | Core + reflected Table (ADR-0017) |
| 노드 카탈로그 | 7종 (SOURCE_API/SQL_TRANSFORM/...) | 13+ (MAP_FIELDS/SQL_INLINE/SQL_ASSET/...) |
| API key scope | retailer_allowlist (1차원) | domain_resource_allowlist (JSONB) |
| 표준화 | HyperCLOVA 임베딩 + 3단계 폴백 | + alias-only (POS payment_method) |

**v1 은 변경 금지**. Phase 5 동안 v1 endpoint / mart schema / 화면은 동결.
v2 는 *옆에* 추가되고, 도메인별 cutover_flag (Phase 5.2.5) 로 점진 전환.

## 5층 구조

```
┌─────────────────────────────────────────────┐
│  외부 (사업측 / 운영자 / 외부 API 소비자)        │
└──────────────┬──────────────────┬───────────┘
               │ admin UI         │ /public/v2
┌──────────────▼──────────────────▼───────────┐
│  HTTP — FastAPI                              │
│   /v1/*  /v2/*  /public/v1/*  /public/v2/*  │
└──────────────┬──────────────────┬───────────┘
               │ async            │ sync (RLS)
┌──────────────▼──────────────────▼───────────┐
│  Domain — registry / nodes_v2 / guardrails  │
│   provider / standardization / shadow_run   │
└──────────────┬──────────────────┬───────────┘
               │                  │
┌──────────────▼─────┐    ┌───────▼───────────┐
│  PostgreSQL 16      │    │  Worker (Dramatiq) │
│  + pgvector + RLS   │    │  + Redis Streams   │
│  schemas:           │    │  + Cron / Backfill │
│    raw / mart       │    └────────────────────┘
│    domain.* / pos_mart
│    audit / ctl / wf │
└─────────────────────┘
```

## 데이터 흐름 (v2 generic)

1. **수집** — `/v1/ingest` 또는 worker (CDC/poll) 가 `raw.raw_object` 적재.
2. **resource_selector** — `domain.source_contract.resource_selector_json` 가
   raw payload 를 (domain, resource) 로 분기.
3. **MAP_FIELDS** — `domain.field_mapping` 의 transform_expr (`text.trim($name)`
   등) 적용 → sandbox table.
4. **SQL_INLINE / SQL_ASSET** — sandbox 테이블 변환. INLINE = 임시, ASSET =
   APPROVED 만 production.
5. **DQ_CHECK** — `domain.dq_rule` 로 row_count_min / null_pct / custom_sql.
6. **STANDARDIZE** — agri 는 임베딩 + 3단계, pos 는 alias-only.
7. **LOAD_TARGET** — `domain.load_policy` (append_only / upsert / scd_type_2 /
   current_snapshot) 로 mart 적재.
8. **외부 노출** — `/public/v2/{domain}/{resource}/latest` + Redis 캐시.

## 도메인 등록 6개 (Phase 5 종료 시점)

| 도메인 | 상태 | 노트 |
|---|---|---|
| agri | PUBLISHED | v1 mart 그대로 + v2 alias (AGRI_PRICE_FACT 등) |
| pos | PUBLISHED | STEP 9 추상화 검증 시험지 (mock 데이터) |
| (추가 예정) | — | Phase 6 — 사업측 요청 도메인 |

## 핵심 가드레일 7+5축

**7종 (Phase 5.2.0):**
1. ALLOWED_SCHEMAS (도메인 인지)
2. DROP/DELETE/TRUNCATE 차단
3. mart 변경 상태머신 DRAFT→REVIEW→APPROVED→PUBLISHED
4. source schema versioning + compat check
5. DQ custom_sql preview + timeout
6. LOAD_TARGET = registry 등록 테이블만
7. domain registry review (ADMIN 승인)

**5축 (Phase 5.2.8):**
1. 수집 (poll_interval / batch_size / rate_limit)
2. Worker/Queue (domain별 routing + backpressure)
3. DB/Schema (partition / JSONB linter / row size)
4. DQ/SQL (timeout_ms / sample_limit / max_scan_rows)
5. Backfill (chunk + checkpoint + parallel cap)

## Strangler Pattern 의 종착점

Phase 5 종료 시점에 v1 은 *살아 있지만 deprecated* 상태:
- `retailer_allowlist` → 자동 매핑 (Phase 7 제거 검토)
- `mart.product_master` 등 v1 테이블 → v2 logical alias (`AGRI_PRODUCT`) 로도 접근
- v1 endpoint URL 은 *영구 호환* (외부 사용자 계약)

> Phase 6 = "v1 의 의존을 점진적으로 줄이면서 새 도메인을 본격 운영" — 이 문서의
> 다음 단계.
