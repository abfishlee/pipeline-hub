# 환경 분리 (local / dev / staging / prod)

**한 줄:** 코드는 로컬에서 짜고 → 공용 개발 환경에서 통합 테스트 → 운영 리허설 환경(staging)에서 최종 확인 → 진짜 서비스(prod)에 올린다.

---

## 1. 왜 환경을 분리하나?

- **새 코드가 고객에게 바로 노출되면 위험.** 하나의 버그가 전체 사고.
- **데이터 섞임 방지.** 개발용 가짜 데이터와 실데이터가 섞이면 안 됨.
- **권한 분리.** prod는 최소 인원만 접근.
- **학습/훈련 공간.** 운영팀이 연습할 곳이 필요.

---

## 2. 4단계 환경 (Phase별 다름)

### Phase 1~3 (사용자 + Claude 개발)

| 환경 | 어디서 돌아감 | 용도 |
|---|---|---|
| **local** | 개발자 노트북 Docker | 코드 쓰는 중 수시 테스트 |
| **dev** | NCP VM 1대 (docker compose) | PR 머지 후 통합 테스트 |

→ staging/prod는 **이 시점엔 없어도 됨.** 고객이 없고 내부 테스트만 하기 때문.

### Phase 4 (운영팀 6~7명 합류 시)

| 환경 | 어디서 돌아감 | 용도 |
|---|---|---|
| **local** | 개발자 노트북 Docker | 개발 |
| **staging** | NKS `datapipeline-staging` namespace | **prod 배포 전 리허설 / 훈련** |
| **prod** | NKS `datapipeline-prod` namespace | **실제 고객 서비스** |

→ dev 환경은 local + PR 단위 자동 테스트로 흡수.

---

## 3. staging vs prod 상세 비교

| 항목 | staging | prod |
|---|---|---|
| **목적** | prod 배포 전 검증 / 운영팀 훈련 | 실제 서비스 운영 |
| **고객** | 없음 (내부만) | 실제 외부 소비자 |
| **데이터** | prod 스냅샷의 **마스킹된 복제** | 실데이터 |
| **DB** | NCP Cloud DB `datapipeline-staging` (vCPU 2, 100GB) | NCP Cloud DB `datapipeline-prod` (vCPU 4+, 300GB+) |
| **Object Storage** | `datapipeline-raw-staging` bucket | `datapipeline-raw-prod` bucket |
| **도메인** | `stg-ops.datapipeline.co.kr`, `stg-api.datapipeline.co.kr` | `ops.datapipeline.co.kr`, `api.datapipeline.co.kr` |
| **외부 API 키** | **샌드박스 모드** (CLOVA OCR 테스트 엔드포인트, OpenAI 별도 키) | 실서비스 키 |
| **배포 시점** | feature merge 즉시 | staging 검증 후 수동 승인 |
| **배포 주체** | 개발팀 + 운영팀 누구나 (연습) | 운영팀 승인자만 |
| **트래픽 부하** | 소량, 합성 부하 테스트 | 실트래픽 (10만~30만/일) |
| **모니터링 알람** | 로그만 (알람 없음) | **Slack 즉시 알람** |
| **장애 시 영향** | 내부만 | **회사/고객 영향** |
| **백업** | 주 1회 | 일 1회 + WAL PITR |
| **롤백** | `git revert` → Argo CD sync | `git revert` + 승인 필요 |

---

## 4. 각 환경의 설정 관리

```
backend/app/config.py
  ↓ APP_ENV 환경변수 읽음

local  → .env (git 제외)
dev    → NCP VM /opt/app/.env
staging → NKS ConfigMap + ExternalSecret (staging namespace)
prod   → NKS ConfigMap + ExternalSecret (prod namespace)
```

**APP_ENV 값에 따라 달라지는 것:**
- 로그 레벨 (`DEBUG` / `INFO`)
- 로그 포맷 (`pretty` / `json`)
- 외부 API base URL (sandbox / production)
- rate limit 값
- CORS 화이트리스트
- Sentry 활성화

---

## 5. 데이터 흐름 (코드 배포 기준)

```
[개발자 로컬]  → git push
       │
       ▼
[GitHub PR + CI]  자동 테스트 (lint, type, unit, integration)
       │
       ▼ (승인 + merge to main)
[GitHub Actions]  이미지 빌드 → NCP Container Registry
       │
       ├─→ Phase 1~3: SSH로 dev VM에 docker compose pull
       │
       └─→ Phase 4:
             [staging 자동 배포]  Argo CD 즉시 sync
                     │
                     ▼
             (운영팀 수동 테스트 / 승인)
                     │
                     ▼
             [prod 배포]  tag 생성 → prod Argo CD sync
```

---

## 6. 데이터베이스 환경 분리 (중요)

**절대 금지:**
- staging에서 prod DB 조회 금지
- 로컬에서 prod Cloud DB 접속 금지 (보안 그룹 차단)
- prod 데이터를 staging에 **마스킹 없이** 복사 금지 (개인정보 없더라도 원칙)

**권장 운영:**
- staging 데이터는 **prod 일부 샘플 + 합성 데이터**로 채움
- 스키마 변경(Alembic migration)은 **staging에서 먼저** 적용 → 검증 → prod
- `pg_dump` 기반 주기적 마스킹 복사 스크립트 준비 (Phase 4)

---

## 7. "언제 staging이 필요해지나" 판단 기준

**아래 중 2개 이상 해당되면 staging 환경 구축 필요:**
- [ ] 외부 고객이 서비스를 씀 (Public API 오픈)
- [ ] 운영팀이 별도 존재 (개발자 아닌 사람이 배포)
- [ ] 하루 매출/핵심 KPI가 걸림
- [ ] 데이터 손실 시 복구 불가능
- [ ] 스키마 변경이 자주 있고, 마이그레이션 리스크가 큼

→ 우리 프로젝트는 **Phase 4(외부 공개 + 운영팀 합류) 시점에 4~5개 모두 해당**되므로 staging 필수.

---

## 8. Phase별 결정 요약

| 시점 | 환경 구성 | 비용 |
|---|---|---|
| 지금 (Phase 1) | local + dev(NCP VM 1대) | 약 5~10만/월 |
| Phase 2 말 | local + dev (그대로) | 동일 |
| Phase 3 말 | local + dev (그대로) | 동일 |
| **Phase 4 시작** | local + staging(NKS) + prod(NKS) | 약 120~180만/월 |

---

## 9. Claude에게 환경 관련 지시 예시

```
"APP_ENV=local 일 때와 APP_ENV=prod 일 때의 config.py 차이를 확인하고,
staging 환경도 지원하도록 추가해줘. docs/ENVIRONMENTS.md 4절에 따라."

"staging 환경 배포를 위한 Argo CD Application YAML을 
infra/k8s/argocd/app-staging.yaml 로 만들어줘.
docs/ENVIRONMENTS.md 3절의 리소스 명세대로."

"로컬에서 prod DB에 실수로 접속 안 되게 config.py에서 가드 넣어줘.
APP_ENV=local에서 APP_DATABASE_URL이 prod 패턴이면 에러."
```

---

## 10. 한 줄 요약

> **Phase 1~3: local + dev (단순) / Phase 4: local + staging + prod (NKS 네임스페이스 분리). staging은 운영팀의 연습장이자 prod 배포 전 리허설 무대.**
