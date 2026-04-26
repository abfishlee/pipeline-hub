# Staging 운영 Runbook (회사 서버)

> 환경: Ubuntu 24.04.4 LTS @ 172.30.1.131 (사내망), D-1 all-in-one Docker Compose,
> ssl_mode A (HTTP only :8080).
> 첫 배포: `scripts/staging_bootstrap.sh` 실행.
> 본 문서: 일상 운영 + 트러블슈팅.

---

## 0. 진입 URL

| 용도 | URL | 비고 |
|---|---|---|
| 사용자 진입 (frontend) | http://172.30.1.131:8080 | 메인 |
| Backend 직접 (디버깅) | http://172.30.1.131:8000/docs | OpenAPI |
| MinIO 콘솔 (관리자) | http://172.30.1.131:9001 | minioadmin / `.env.staging` 의 MINIO_ROOT_PASSWORD |
| Postgres (psql) | `psql -h 172.30.1.131 -p 5434 -U app datapipeline` | password = `.env.staging` 의 POSTGRES_PASSWORD |
| Redis | `redis-cli -h 172.30.1.131 -p 6380 ping` | 사내망 only — password 없음 |

---

## 1. 일상 명령

배포 디렉토리는 `/opt/datapipeline` 가정.

```bash
cd /opt/datapipeline
COMPOSE="sudo docker compose -f infra/docker-compose.staging.yml --env-file .env.staging"
```

### 시작 / 종료
```bash
$COMPOSE up -d                      # 전체 기동
$COMPOSE up -d backend worker       # 일부만
$COMPOSE stop backend worker        # 종료 (state 보존)
$COMPOSE down                       # 종료 + 컨테이너 삭제 (volume 보존)
$COMPOSE down -v                    # 종료 + volume 까지 삭제 ⚠ 데이터 손실
```

### 로그
```bash
$COMPOSE logs -f backend                   # 실시간
$COMPOSE logs --tail 200 worker            # 최근 200줄
$COMPOSE logs frontend backend             # 동시
$COMPOSE logs --since 30m backend          # 30분 전부터
```

### 상태 확인
```bash
$COMPOSE ps                                # 컨테이너 + healthcheck
sudo docker stats --no-stream              # CPU/RAM 스냅샷
curl -fsS http://localhost:8000/healthz    # backend liveness
curl -fsS http://localhost:8080/healthz    # frontend liveness
```

### 재시작
```bash
$COMPOSE restart backend worker            # 일부만
$COMPOSE up -d --force-recreate backend    # 완전 재생성 (env 변경 후)
```

---

## 2. Migration / 코드 갱신

### 새 commit 반영
```bash
cd /opt/datapipeline
git pull --ff-only
$COMPOSE build backend frontend            # 이미지 재빌드
$COMPOSE run --rm migrate                  # alembic upgrade head
$COMPOSE up -d --force-recreate backend worker frontend
```

### 수동 alembic
```bash
$COMPOSE run --rm migrate alembic current
$COMPOSE run --rm migrate alembic history --verbose
$COMPOSE run --rm migrate alembic downgrade -1   # 1단계 rollback
```

### admin user 추가/변경
```bash
$COMPOSE run --rm migrate \
  python /app/scripts/seed_admin.py \
    --login_id ops \
    --password '<강력비밀>' \
    --email ops@company.com \
    --role ADMIN
```

---

## 3. 백업 (D-1 staging — 수동)

### Postgres 백업
```bash
sudo docker exec dp_staging_postgres \
  pg_dump -U app -d datapipeline -F c -f /tmp/dp.dump
sudo docker cp dp_staging_postgres:/tmp/dp.dump /backup/$(date +%Y%m%d).dump
```

### MinIO 백업
```bash
# 컨테이너 안 mc 사용.
sudo docker run --rm --network datapipeline-staging_default \
  -v /backup/minio:/backup \
  minio/mc:latest /bin/sh -c "
    mc alias set s http://minio:9000 minioadmin <PASSWORD>
    mc mirror s/datapipeline-staging /backup/$(date +%Y%m%d)
  "
```

### 정기 백업 cron 권장
```cron
# /etc/cron.d/datapipeline-staging-backup
0 3 * * * fishnoon cd /opt/datapipeline && bash scripts/backup_staging.sh
```
(스크립트는 별도 작성 — Phase 6.)

---

## 4. 일반 트러블슈팅

### 시나리오 A — backend 가 healthy 안 됨
1. `$COMPOSE logs backend --tail 50` 로 stack trace.
2. 자주 발생:
   - `connection refused` → postgres 가 아직 안 떴거나 password 불일치 → `$COMPOSE ps` 확인
   - `migration not applied` → `$COMPOSE run --rm migrate`
   - `JWT_SECRET missing` → `.env.staging` 확인
3. fix 후 `$COMPOSE up -d --force-recreate backend`.

### 시나리오 B — worker 가 메시지 처리 안 함
1. Redis 도달 가능?
   ```bash
   sudo docker exec dp_staging_redis redis-cli ping  # PONG
   ```
2. DLQ 누적 확인:
   ```bash
   sudo docker exec dp_staging_postgres \
     psql -U app -d datapipeline -c \
     "SELECT origin, COUNT(*) FROM run.dead_letter WHERE replayed_at IS NULL GROUP BY origin"
   ```
3. worker process 수 부족 → compose 의 `--processes 2 --threads 4` 조정.

### 시나리오 C — Frontend 가 API 호출 실패 (CORS / 502)
1. nginx 가 backend 에 접근 가능?
   ```bash
   sudo docker exec dp_staging_frontend wget -qO- http://backend:8000/healthz
   ```
2. CORS — `.env.staging` 의 `APP_CORS_ORIGINS` 가 frontend URL 포함?
3. backend logs 에 5xx 없는지 확인.

### 시나리오 D — 디스크 풀
```bash
df -h /                                  # 전체
sudo docker system df                    # docker 사용량
sudo docker system prune -a              # 미사용 이미지/컨테이너/네트워크
sudo docker volume prune                 # ⚠ 미사용 volume — staging_*_data 보호
```

### 시나리오 E — 8080 응답 없음
1. `sudo ss -tlnp | grep 8080` — frontend 컨테이너가 listen?
2. ufw 가 차단? `sudo ufw status verbose | grep 8080`
3. 사내 방화벽 / 라우터 ACL — 회사 IT 팀 문의.

---

## 5. 비밀값 회전

### Postgres password
```bash
NEW_PW="<random_32>"
sudo docker exec -e PGPASSWORD=<old_pw> dp_staging_postgres \
  psql -U app -d datapipeline -c "ALTER USER app WITH PASSWORD '$NEW_PW'"
# .env.staging 갱신
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$NEW_PW/" .env.staging
$COMPOSE up -d --force-recreate backend worker
```

### MinIO key
MinIO admin 콘솔 → User → 키 회전 → `.env.staging` 의 `MINIO_ROOT_PASSWORD` /
`APP_OS_SECRET_KEY` 갱신 → backend/worker 재시작.

### JWT secret
```bash
NEW=$(openssl rand -hex 32)
sed -i "s/^APP_JWT_SECRET=.*/APP_JWT_SECRET=$NEW/" .env.staging
$COMPOSE up -d --force-recreate backend worker
# ⚠ 기존 발급된 모든 JWT 무효화 — 사용자 재로그인 필요.
```

---

## 6. Phase 5 v2 generic 추가 운영 명령

### 새 도메인 yaml 등록
```bash
# domains/<new>.yaml + migration <NNN>_<new>_mart.py 생성 후:
git pull --ff-only
$COMPOSE run --rm migrate                    # 새 migration 적용
$COMPOSE restart backend worker
```

### Cutover 콘솔
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login_id":"admin","password":"<ADMIN_PASSWORD>"}' | jq -r .access_token)

# diff report
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v2/cutover/diff-report?domain_code=agri&resource_code=PRICE_FACT" \
  | jq

# cutover 실행
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"domain_code":"agri","resource_code":"PRICE_FACT","target_path":"v2"}' \
  http://localhost:8000/v2/cutover/apply
```

### SLO baseline 측정
```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/v2/perf/baseline/measure | jq

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/v2/perf/slo/summary?window_minutes=60" | jq
```

### Backfill (1년치 365 chunks)
```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "domain_code": "agri",
    "resource_code": "PRICE_FACT",
    "target_table": "mart.price_fact",
    "start_at": "2025-01-01T00:00:00+00:00",
    "end_at":   "2026-01-01T00:00:00+00:00",
    "chunk_unit": "day",
    "chunk_size": 1,
    "max_parallel_runs": 2
  }' \
  http://localhost:8000/v2/backfill | jq
```

---

## 7. Phase 6 NKS 이관 시 주의

본 staging 은 D-1 all-in-one. NKS 이관 (Phase 6) 시:
- Postgres → NCP Cloud DB for PostgreSQL (외부 endpoint).
- Redis → NCP Cloud DB for Redis.
- MinIO → NCP Object Storage.
- Frontend → NCP CDN + ingress.
- Worker → 별도 Deployment + HPA.
- Secret → NCP Secret Manager.

`.env.staging` → ConfigMap + Secret. `docker-compose.staging.yml` → `infra/k8s/*.yaml`.

자세한 절차는 [docs/ops/NKS_DEPLOYMENT.md](./NKS_DEPLOYMENT.md) 참고 (Phase 4 시점 작성, Phase 6 갱신 예정).

---

## 8. 비상 종료 + 복구

### 전체 비상 종료
```bash
$COMPOSE down                              # 컨테이너만 (volume 보존)
```

### Postgres 데이터 복구 (from dump)
```bash
sudo docker exec -i dp_staging_postgres \
  psql -U app -d datapipeline < /backup/20260427.dump
```

### 처음부터 다시 (⚠ 모든 데이터 삭제)
```bash
$COMPOSE down -v
rm /opt/datapipeline/.env.staging
bash /opt/datapipeline/scripts/staging_bootstrap.sh
```

---

## 9. 모니터링 (현재 staging 미포함 — Phase 6 추가 예정)

현재 staging compose 는 *Prometheus / Grafana / Loki 제외* (단순화).

수동 모니터:
- `sudo docker stats --no-stream` — CPU/RAM
- `sudo docker logs -f` — log
- `$COMPOSE ps` — health

Phase 6 이관 시 dev compose 의 prometheus/grafana 를 staging 에 추가하거나 NKS
의 표준 monitoring stack 으로 대체.

---

## 10. 빠른 참조 — 자주 쓰는 명령

```bash
cd /opt/datapipeline
COMPOSE="sudo docker compose -f infra/docker-compose.staging.yml --env-file .env.staging"

# 상태
$COMPOSE ps
curl -s http://localhost:8000/healthz && echo OK
curl -s http://localhost:8080/healthz && echo OK

# 로그
$COMPOSE logs -f backend worker --tail 100

# 재시작
$COMPOSE restart backend worker

# 새 commit 반영
git pull --ff-only && $COMPOSE build && $COMPOSE run --rm migrate && \
  $COMPOSE up -d --force-recreate backend worker frontend

# DB 진입
sudo docker exec -it dp_staging_postgres psql -U app datapipeline

# Redis 진입
sudo docker exec -it dp_staging_redis redis-cli
```
