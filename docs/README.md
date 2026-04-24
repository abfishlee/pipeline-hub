# docs/ — 설계 문서 목차

이 디렉토리는 Claude가 개발할 때 참조할 문서 모음이다. 루트 `CLAUDE.md`에서 이 README로 진입한다.

## 읽는 순서

1. `00_PROJECT_CONTEXT.md` — 프로젝트 배경, 비즈니스 도메인, 수집 채널 개요
2. `01_TECH_STACK.md` — 확정된 기술 스택 (NCP 기반)
3. `02_ARCHITECTURE.md` — 레퍼런스 아키텍처, 폴더 구조, 컴포넌트 간 통신
4. `03_DATA_MODEL.md` — 전체 DB 스키마 DDL
5. `04_DOMAIN_MODEL.md` — 상품/판매자/유통사/가격/표준코드 도메인 설계
6. `05_CONVENTIONS.md` — 코드/커밋/브랜치/테스트 컨벤션
7. `06_DATA_FLOW.md` — 수집→마스터→서비스 10단계 + 각 단계 기술
8. `07_CORE_TECHNOLOGIES.md` — Kubernetes/Airflow/Kafka 개념과 역할
9. `ENVIRONMENTS.md` — dev/staging/prod 환경 분리

## 단계별 구현 문서

- `phases/PHASE_1_CORE.md` — Core Foundation (수집 API + Raw 보존 + 기본 UI)
- `phases/PHASE_2_RUNTIME.md` — Worker + DAG Runtime + OCR + 표준화
- `phases/PHASE_3_VISUAL_ETL.md` — Visual Pipeline Designer + SQL Studio
- `phases/PHASE_4_ENTERPRISE.md` — Crowd 검수 + DQ 게이트 + CDC + 외부 서비스 API
- `phases/CURRENT.md` — (자동 생성) 현재 진행 중인 Phase 표시

## 운영 문서

- `ops/NCP_DEPLOYMENT.md` — **Phase 1~3** Docker Compose 단일 VM 배포
- `ops/NKS_DEPLOYMENT.md` — **Phase 4** NKS 이관 (운영팀 6~7명 합류 대비)
- `ops/MONITORING.md` — (Phase 2에서 생성) 관제/로그/지표

## Airflow 문서

- `airflow/LEARNING_GUIDE.md` — Airflow 초심자 10단계 학습 가이드 (Phase 2 착수 전 숙지)
- `airflow/INTEGRATION.md` — Airflow / Dramatiq / Visual ETL 역할 분담 원칙

## Claude 협업 가이드

- `HOW_TO_WORK_WITH_CLAUDE.md` — 사용자가 Claude에게 명령하는 효과적 방법 (템플릿 10개 포함)

## 원본 설계 자료

- `../world_class_data_pipeline_design.md` — 원본 설계 제안서 (참고용)
- `../world_class_data_pipeline_design.pdf` — PDF 버전 + 다이어그램
- `../_pdf_extracted/` — PDF에서 추출된 페이지/이미지

## 문서 업데이트 원칙

- 구현이 설계와 달라지면 **문서부터 먼저 수정**하고 코드 반영.
- Phase 완료 시 해당 `PHASE_*.md`의 체크리스트를 모두 ✅ 로 바꾸고, `CURRENT.md`를 다음 Phase로 이동.
- 새로운 도메인 용어가 생기면 `04_DOMAIN_MODEL.md` 용어집에 추가.
