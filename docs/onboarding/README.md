# 운영자 Onboarding 자료

Phase 5 (v2 generic platform) 완료 시점 갱신.

## 누구를 위한 문서인가
- **신규 합류 운영자** (DBA / SRE / Data Engineer) — 처음 7~14일 안에 시스템을 이해하고
  새 도메인 1개 추가까지 자율 수행하는 것을 목표.
- 기존 멤버 — 새 기능/정책 (v2 generic / shadow run / cutover / SLO) 의 reference.

## 5종 핵심 문서

| # | 문서 | 다루는 범위 |
|---|---|---|
| 1 | [01_system_overview.md](./01_system_overview.md) | 시스템 전체 그림 / v1 vs v2 / Strangler Pattern |
| 2 | [02_local_dev.md](./02_local_dev.md) | 로컬/회사서버 실행 + .env / docker-compose / migration |
| 3 | [03_domain_playbook.md](./03_domain_playbook.md) | **신규 도메인 1개 추가 절차 (12 단계)** ★ |
| 4 | [04_operations_runbook.md](./04_operations_runbook.md) | 장애 대응 / DLQ / shadow_diff / cutover / backfill |
| 5 | [05_security_rls_apikey.md](./05_security_rls_apikey.md) | 권한 / RLS / API Key / multi-domain scope |

## 보조 문서 (빈도 낮음, 필요할 때)

| 문서 | 용도 |
|---|---|
| [v2_etl_designer.md](./v2_etl_designer.md) | Field Mapping / Mart Designer / DQ Builder UI 사용법 |
| [dq_rule_authoring.md](./dq_rule_authoring.md) | DQ rule 작성 가이드 + custom_sql sandbox |
| [backfill_operations.md](./backfill_operations.md) | 1년치 backfill chunk + checkpoint 운영법 |
| [provider_registry.md](./provider_registry.md) | OCR/Crawler/HTTP provider 등록 + 우선순위 |
| [perf_guards_explained.md](./perf_guards_explained.md) | 5축 가드레일 + 10종 SLO 임계값 + Performance Coach |

## 7~14 일 학습 경로 (추천)

| Day | 활동 | 문서 |
|---|---|---|
| 1 | 시스템 개요 + git clone + 로컬 실행 | 01, 02 |
| 2 | v1 농축산물 PRICE_FACT 1건 직접 수집 | 02 + dev/PHASE_1_E2E |
| 3 | v2 generic 의 agri.yaml 구조 이해 | 01 + ADR-0017 |
| 4 | shadow_diff / cutover 콘솔 둘러보기 | 04 |
| 5 | DQ rule 1개 작성 + dry-run | dq_rule_authoring |
| 6 | Mart Designer 로 새 column ALTER 시도 | v2_etl_designer |
| 7 | API Key 발급 + multi-domain scope | 05 |
| 8~12 | **새 도메인 1개 직접 추가 (POS 모델 답습)** | 03 ★ |
| 13 | backfill 7일치 시도 | backfill_operations |
| 14 | 회고 + Phase 6 backlog 검토 | PHASE_6_FIELD_VALIDATION |

## 즉시 도움이 필요할 때

- 시스템 장애: `docs/ops/MONITORING.md` 의 알림 채널
- 코드 변경: PR 리뷰는 ADMIN 1명 + 도메인 EDITOR 1명 (Phase 5 정책)
- v2 추상화 한계: ADR-0017 / 0019 / 0020 참고 + `/ultrareview` 로 클라우드 리뷰 가능
- 사용자(=Product Owner) 결정 필요: 사용자 1명 직접 문의 (Phase 5 까지 1+Claude 체제)

## ADR 빠른 참조

| ADR | 주제 |
|---|---|
| 0017 | Hybrid ORM 전략 (v1=ORM, v2=Core+reflected) |
| 0018 | v2 generic 회고 + 추상화 KPI ★ Phase 5 결산 |
| 0019 | POS 도메인 추가 KPI 검증 결과 |
| 0020 | Kafka 도입 트리거 (현재 미도입) |
