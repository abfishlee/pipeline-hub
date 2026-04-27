# Airflow 운영 가이드

**최종 갱신:** Phase 8.6 (2026-04-27)
**대상:** 운영자 / 개발자

---

## 0. Airflow 의 역할

본 시스템에서 Airflow 는 **"스케줄 자동 발사기"** 역할만 담당합니다 — 사용자가 ETL Canvas 에서
설계한 워크플로의 `schedule_cron` 을 매분 평가하여 backend 의 trigger endpoint 를 호출합니다.

**Airflow 가 안 켜져 있어도 시스템 자체는 동작합니다** — 다만 *수동 실행* 만 가능 (Canvas 의 [실행] 버튼).
schedule_cron 자동 발사가 필요하면 Airflow 를 기동해야 합니다.

---

## 1. 가동 중인 DAG 6 종

| DAG 이름 | 주기 | 역할 |
|---|---|---|
| `hello_pipeline` | 매분 (smoke) | Airflow 정상 가동 확인용 — 운영 무관 |
| **`scheduled_pipelines`** | **매분** | **★ Canvas 워크플로 cron 자동 trigger — 본 시스템의 핵심 발사기** |
| `master_merge_daily` | 매일 03:00 KST | master 자동 머지 |
| `cdc_lag_monitor` | 5 분마다 | CDC slot lag 감시 (CDC 활성 시) |
| `public_api_usage_daily` | 매일 00:30 | Public API 사용량 일별 집계 |
| `partition_archive_monthly` | 매월 1 일 | 오래된 파티션 archive |

---

## 2. 로컬 개발 — 기동 절차

### 2.1 사전 준비
- backend 가 가동 중 (`http://127.0.0.1:8000` /healthz 응답)
- `.env` 에 다음 변수 설정
  ```
  APP_AIRFLOW_INTERNAL_TOKEN=<랜덤 토큰>
  AIRFLOW_BACKEND_INTERNAL_URL=http://host.docker.internal:8000
  ```

### 2.2 기동
```bash
cd e:/dev/datapipeline
docker compose -f infra/docker-compose.yml \
               -f infra/docker-compose.airflow.override.yml \
               --env-file .env up -d airflow-init airflow-webserver airflow-scheduler airflow-worker
```

### 2.3 확인
```bash
# 컨테이너 가동 확인
docker ps | grep airflow

# webserver UI: http://localhost:8080  (admin / admin — override 첫 기동 시 자동 생성)

# scheduled_pipelines DAG 가 매분 가동되는지 확인
docker logs -f infra-airflow-scheduler-1 | grep scheduled_pipelines
```

### 2.4 워크플로 cron 실증
1. Frontend (`/v2/pipelines/designer`) 에서 워크플로 1개 PUBLISHED
2. Cron Picker 로 "1 분마다" 선택 + 활성 + 스케줄 저장
3. 1~2 분 안에 `/pipelines/runs` 에 신규 RUNNING run 1건 자동 생성 확인
4. backend 로그에 `pipelines.internal.runs.created` log line 확인

---

## 3. 운영 환경 (NKS) — Phase 4

운영 환경에서는 docker-compose 대신 **Helm chart 의 Airflow** 를 사용 (`infra/k8s/helm/airflow/`).
ExternalSecrets Operator 가 NCP Secret Manager 에서 `BACKEND_INTERNAL_TOKEN` 을 주입.

자세한 절차는 `docs/ops/NKS_DEPLOYMENT.md`.

---

## 4. 트러블슈팅

| 증상 | 원인 후보 | 조치 |
|---|---|---|
| schedule_cron 활성화했는데 run 이 자동 생성 안 됨 | Airflow scheduler 가 죽었거나 안 켜져 있음 | `docker ps | grep scheduler` 확인. 없으면 §2.2 재시동 |
| Airflow webserver 5초마다 재시작 | `airflow-init` 가 실패 (DB 마이그레이션 안 끝남) | `docker logs infra-airflow-init-1` 확인 후 재시도 |
| `scheduled_pipelines` DAG 가 backend 401 | `APP_AIRFLOW_INTERNAL_TOKEN` 불일치 | `.env` 의 토큰을 backend 와 Airflow Variable 양쪽 동일하게 |
| run 이 만들어졌지만 노드가 PENDING 그대로 | Dramatiq worker 미가동 | `docker ps | grep worker` 확인 |
| Operations Dashboard 의 "Auto Dispatcher" 가 STALE | inbound dispatcher (5초 polling) 가 죽음 — Airflow 와 별개 | backend 컨테이너 재시작 |

---

## 5. 비활성 운영

Airflow 를 일시 끄려면:
```bash
docker compose -f infra/docker-compose.yml \
               -f infra/docker-compose.airflow.override.yml \
               stop airflow-webserver airflow-scheduler airflow-worker
```
이 상태에서도 시스템은 정상 — 다만 수동 실행만 가능.
