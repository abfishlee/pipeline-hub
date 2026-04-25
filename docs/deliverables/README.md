# 산출물 (Customer-facing Deliverables)

본 디렉토리는 고객 / 사업 결정권자 / 운영자에게 제공할 산출물 모음. 모두 HTML 형식이라
별도 도구 설치 없이 브라우저에서 열고 **Chrome → 인쇄 → PDF로 저장** 만 누르면 PDF 추출.

## 산출물 목록

| 파일 | 대상 독자 | 내용 | 페이지 (예상) | 권장 용지 |
|---|---|---|---|---|
| [01_system_overview.html](./01_system_overview.html) | 사업 결정권자 / 기술 책임자 | 시스템 목표 / 4계층 모델 / 핵심 기능 + 기술 스택 / 10단계 파이프라인 / 채널 7종 / Phase 진행 / ADR | ~14 페이지 | A4 세로 |
| [02_user_manual.html](./02_user_manual.html) | 운영자 / 분석가 / 관리자 | 채널별 (POS API / DB / Crawl / OCR) 9단계 프로세스 + 스케줄 / Backfill / 재실행 + SQL Studio 라이프사이클 + 트러블슈팅 | ~16 페이지 | A4 세로 |
| [03_erd.html](./03_erd.html) | DBA / 데이터 모델러 / 아키텍트 | Schema 8종 + 30+ 테이블 + 47 FK 전체 ERD (SVG) + Schema 별 상세 + 파티션/벡터/인덱스 정책 | ~6 페이지 | **A3 가로** |

## PDF 추출 방법

### Chrome / Edge

1. 파일을 더블클릭 또는 `file:///e:/dev/datapipeline/docs/deliverables/01_system_overview.html` 로 열기
2. `Ctrl + P` → **인쇄 대상**: `PDF로 저장`
3. **레이아웃**: 세로, **여백**: 기본, **배경 그래픽**: ✅ 체크 (SVG 색상 보존)
4. **저장**

### Firefox

1. 파일 열기
2. `Ctrl + P` → **대상**: `PDF로 저장` 또는 `Microsoft Print to PDF`

## 화면 캡처 추가 (02_user_manual.html)

매뉴얼의 `[화면 캡처 자리]` 점선 박스는 운영자가 실 인스턴스에서 캡처해 교체합니다:

1. 가이드된 화면 진입 (예: `/pipelines/designer/3`)
2. `Win + Shift + S` (Windows) 또는 `Cmd + Shift + 4` (Mac) 으로 캡처
3. 이미지 파일 (`screenshots/01_designer.png`) 로 저장
4. HTML 의 `<div class="screenshot">...</div>` 를 `<img src="screenshots/01_designer.png" style="max-width:100%; border:1px solid #cbd5e1;"/>` 로 교체
5. 다시 PDF 추출

## 자동 캡처 (선택)

Playwright 로 자동화하고 싶으면:

```bash
cd frontend
pnpm add -D @playwright/test
pnpm exec playwright install chromium

# tests/perf/test_designer_render.spec.ts 와 같은 스타일로
# capture 스크립트 작성 → docs/deliverables/screenshots/ 에 저장
```

(현재는 Playwright 가 설치되지 않아 placeholder 박스만 들어 있음.)

## 갱신 주기

- **01_system_overview**: Phase 별 1회 (Phase 4 진입 시 갱신)
- **02_user_manual**: 메뉴 / 기능 변경 시 즉시 갱신 (Phase 4 의 Crowd 정식 / Public API 추가 시 큰 갱신)
