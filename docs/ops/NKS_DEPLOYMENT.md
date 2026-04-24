# NKS (Naver Kubernetes Service) 배포/이관 가이드

**언제 쓰는가:** Phase 4 진입 시점(운영팀 6~7명 합류)에 Docker Compose 기반 VM 배포에서 NKS로 이관할 때.
**전제:** Phase 1~3에서 "NKS Ready 규칙" (`01_TECH_STACK.md` 1.8)을 지켜왔어야 함.

---

## 1. 왜 Phase 4에서 NKS인가

| 이유 | 설명 |
|---|---|
| **팀 규모** | 운영팀 6~7명 → 네임스페이스/RBAC으로 작업 격리 필요 |
| **독립 배포** | 여러 사람이 동시에 PR 머지/배포 → GitOps(Argo CD)로 충돌 없이 |
| **무중단 운영** | Rolling update + Pod Disruption Budget |
| **자동 복구** | Pod 재시작/노드 교체 자동 |
| **Auto-scale** | 피크 트래픽(30만/일 영수증 시즌) HPA로 대응 |
| **외부 서비스 오픈** | 공개 API라 SLA 99.5%를 안정적으로 |

### 왜 Phase 1~3에는 안 썼나
- 사용자+Claude 2인은 K8s manifest 디버깅에 시간 쓰는 게 손해.
- 스키마/아키텍처 변경이 잦은 초기에 compose가 반복 속도 10배 빠름.

---

## 2. 이관 전 체크 (Phase 1~3 동안 해두었어야 할 것)

| 항목 | 확인 방법 |
|---|---|
| Stateless 컨테이너 | 컨테이너 내부에 파일 저장 없음, Object Storage로만 |
| 설정 env 주입 | 모든 설정 `APP_*` 환경변수 |
| Health endpoint | `/healthz` (liveness), `/readyz` (readiness) 동작 |
| SIGTERM graceful shutdown | 10초 내 종료, in-flight 요청 처리 |
| stdout JSON 로그 | 파일 로깅 0건 |
| Request ID 전파 | 분산 추적 가능 |
| 이미지 빌드 | multi-stage, 이미지 크기 < 500MB, trivy 통과 |
| DB migration 분리 | 앱 시작 시 자동 migrate 안 함 |

**하나라도 안 되어 있으면 이관 전 수정**. 이 문서의 7장(사전 정비) 참조.

---

## 3. 이관 전체 타임라인 (Phase 4, 총 8주)

```
W1~W2 : Terraform 베이스라인, NKS 클러스터 프로비저닝
W2~W3 : Argo CD 설치, staging 네임스페이스 먼저 구축
W3~W4 : Helm Chart 작성, staging 배포 성공
W4~W5 : Observability 스택 (Prometheus+Loki+Grafana) 이관
W5~W6 : Prod 네임스페이스 구축, VM 환경과 병행 운영
W6~W7 : 트래픽 점진 이전 (10% → 50% → 100%)
W7    : VM 환경 종료 (2주 소프트 폐기)
W8    : 운영팀 온보딩 실습 + 런북 정비
```

---

## 4. 인프라 프로비저닝 (Terraform)

### 4.1 디렉토리 구조

```
infra/terraform/ncp/
├── main.tf
├── variables.tf
├── versions.tf
├── backend.tf              # Terraform state → NCP Object Storage
├── modules/
│   ├── vpc/
│   ├── nks/
│   ├── clouddb-pg/
│   ├── clouddb-redis/
│   ├── object-storage/
│   └── container-registry/
└── envs/
    ├── staging/
    │   ├── main.tf         # module 호출
    │   └── terraform.tfvars
    └── prod/
        ├── main.tf
        └── terraform.tfvars
```

### 4.2 NKS 클러스터 변수 (예시)

```hcl
# envs/prod/terraform.tfvars
nks_version         = "1.29"
node_pool_name      = "app-pool"
node_count          = 3
node_spec           = "s2-g3"          # 2 vCPU / 8 GB
node_disk_size_gb   = 100
subnet_cidr         = "10.0.10.0/24"   # private subnet
enable_auto_scale   = true
min_nodes           = 3
max_nodes           = 10
```

### 4.3 최초 실행 순서

```bash
# state backend 준비 (NCP Object Storage 버킷 필요)
cd infra/terraform/ncp/envs/staging
terraform init
terraform plan -out tfplan
terraform apply tfplan

# NKS kubeconfig 얻기
ncp-iam-authenticator update-kubeconfig \
  --region kr --clusterUuid <uuid>

# 접근 확인
kubectl get nodes
```

---

## 5. GitOps — Argo CD 기반

### 5.1 왜 GitOps?

- 여러 운영자가 동시 배포해도 **Git history가 진실의 원천**.
- kubectl apply 남발 → 클러스터 drift 방지.
- 롤백은 `git revert` 한 번.

### 5.2 레포 구조

```
infra/k8s/
├── helm/
│   └── datapipeline/            # 앱 메인 Chart
│       ├── Chart.yaml
│       ├── values.yaml          # 공통 값
│       ├── values-staging.yaml
│       ├── values-prod.yaml
│       └── templates/
│           ├── backend-deployment.yaml
│           ├── backend-service.yaml
│           ├── backend-hpa.yaml
│           ├── worker-transform-deployment.yaml
│           ├── worker-ocr-deployment.yaml
│           ├── worker-crawler-deployment.yaml
│           ├── airflow-*.yaml
│           ├── frontend-deployment.yaml
│           ├── ingress.yaml
│           ├── externalsecret.yaml
│           ├── networkpolicy.yaml
│           ├── pdb.yaml
│           └── servicemonitor.yaml
├── argocd/
│   ├── app-staging.yaml         # Argo CD Application
│   ├── app-prod.yaml
│   └── root-app.yaml            # App of Apps 패턴
├── cluster-addons/
│   ├── ingress-nginx/
│   ├── cert-manager/
│   ├── external-secrets/
│   ├── kube-prometheus-stack/
│   ├── loki-stack/
│   └── argocd/
└── README.md
```

### 5.3 Argo CD 설치

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# 초기 admin 비밀번호
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d
```

### 5.4 App of Apps 패턴

```yaml
# infra/k8s/argocd/root-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/datapipeline
    targetRevision: main
    path: infra/k8s/argocd
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

---

## 6. Helm Chart 핵심 리소스

### 6.1 backend-deployment.yaml (요약)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend-api
spec:
  replicas: {{ .Values.backend.replicas }}
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  selector:
    matchLabels: { app: backend-api }
  template:
    metadata:
      labels: { app: backend-api }
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: backend-api
      containers:
      - name: backend
        image: {{ .Values.image.registry }}/backend:{{ .Values.image.tag }}
        ports: [{ containerPort: 8000 }]
        envFrom:
          - configMapRef: { name: app-config }
          - secretRef:    { name: app-secrets }
        readinessProbe:
          httpGet: { path: /readyz, port: 8000 }
          periodSeconds: 5
        livenessProbe:
          httpGet: { path: /healthz, port: 8000 }
          periodSeconds: 10
        resources:
          requests: { cpu: 200m, memory: 512Mi }
          limits:   { cpu: 1000m, memory: 1Gi }
        lifecycle:
          preStop:
            exec: { command: ["sleep", "10"] }   # 엔드포인트 제거 후 종료
```

### 6.2 HPA (수평 자동 스케일)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: worker-ocr
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: worker-ocr
  minReplicas: 2
  maxReplicas: 6
  metrics:
    - type: External
      external:
        metric:
          name: dramatiq_queue_lag
          selector: { matchLabels: { queue: ocr } }
        target:
          type: AverageValue
          averageValue: "50"     # pod당 대기 메시지 50개 기준 스케일
```

커스텀 메트릭은 `prometheus-adapter` 로 노출 (observability 네임스페이스).

### 6.3 Ingress + TLS

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: datapipeline
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/proxy-body-size: "20m"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts: [ops.datapipeline.co.kr, api.datapipeline.co.kr]
      secretName: datapipeline-tls
  rules:
    - host: ops.datapipeline.co.kr
      http:
        paths:
          - { path: /, pathType: Prefix, backend: { service: { name: frontend,    port: { number: 80 }}}}
          - { path: /api, pathType: Prefix, backend: { service: { name: backend-api, port: { number: 8000 }}}}
          - { path: /airflow, pathType: Prefix, backend: { service: { name: airflow-webserver, port: { number: 8080 }}}}
    - host: api.datapipeline.co.kr
      http:
        paths:
          - { path: /public, pathType: Prefix, backend: { service: { name: backend-api, port: { number: 8000 }}}}
```

### 6.4 External Secrets

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: app-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: ncp-secret-manager
    kind: ClusterSecretStore
  target:
    name: app-secrets
  data:
    - secretKey: APP_DATABASE_URL
      remoteRef: { key: /prod/app/db/url }
    - secretKey: APP_JWT_SECRET
      remoteRef: { key: /prod/app/jwt/secret }
    - secretKey: APP_CLOVA_OCR_SECRET
      remoteRef: { key: /prod/app/clova_ocr/secret }
    # ... 생략
```

### 6.5 NetworkPolicy (최소 권한)

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-api
spec:
  podSelector: { matchLabels: { app: backend-api } }
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - podSelector: { matchLabels: { app: frontend } }
        - namespaceSelector: { matchLabels: { name: ingress-nginx } }
      ports: [{ port: 8000 }]
  egress:
    - to: [{ namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: kube-system }}}]
      ports: [{ port: 53, protocol: UDP }]   # DNS
    - to:
        - ipBlock: { cidr: 10.0.0.0/16 }     # Cloud DB/Redis private IP 범위
    - to:
        - ipBlock: { cidr: 0.0.0.0/0 }       # 외부 OCR/Embedding API
      ports: [{ port: 443 }]
```

### 6.6 DB Migration Job (Helm hook)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate-{{ .Release.Revision }}
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 2
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: {{ .Values.image.registry }}/backend:{{ .Values.image.tag }}
        envFrom:
          - secretRef: { name: app-secrets }
        command: ["alembic", "upgrade", "head"]
```

---

## 7. Phase 1~3 동안 미리 정비해둘 것 (NKS Ready)

각 항목은 Phase 1~2에서 지속적으로 지키면 Phase 4 이관 시 공사 규모를 최소화한다.

### 7.1 컨테이너 이미지
- [ ] `Dockerfile` 은 multi-stage (builder → runtime).
- [ ] distroless 또는 alpine slim 기반.
- [ ] non-root USER로 실행.
- [ ] 이미지 라벨: `org.opencontainers.image.source`, `title`, `version`.
- [ ] `docker scan` 또는 trivy CI에 포함.

### 7.2 애플리케이션
- [ ] `/healthz`, `/readyz` 엔드포인트 (readiness는 DB/Redis ping 포함).
- [ ] SIGTERM 수신 시 FastAPI `lifespan`에서 graceful shutdown.
- [ ] 로그는 stdout JSON.
- [ ] 설정은 `APP_*` 환경변수로만.
- [ ] 상관관계 `X-Request-ID` 헤더 항상 생성/전파.
- [ ] 이미지 내부 파일 쓰기 금지 (로그/임시파일 포함, 필요시 emptyDir 마운트 예정).

### 7.3 DB 마이그레이션
- [ ] alembic을 앱 기동 시 자동 실행하지 말 것.
- [ ] 로컬도 `make migrate` 같은 별도 명령으로 분리 습관.
- [ ] 마이그레이션은 backward-compatible (2-step deploy) 연습.

### 7.4 큐/브로커
- [ ] Dramatiq broker URL은 env에서 받음.
- [ ] Redis 연결 재시도 내장.
- [ ] actor가 멱등성 보장.

### 7.5 Airflow
- [ ] DAG 파일은 `backend/airflow_dags/` 디렉토리 — NKS에서는 ConfigMap 또는 git-sync sidecar로 마운트.
- [ ] Airflow Variables/Connections는 환경별 seed 스크립트로 재현 가능하게.
- [ ] metadata DB는 외부 매니지드 PG로.

---

## 8. 마이그레이션 실행 절차 (Phase 4 W5~W7)

### 8.1 병행 운영 기간 설계

```
┌──────────────┐       ┌──────────────┐
│  기존 VM     │       │  NKS Prod    │
│ (docker      │       │              │
│  compose)    │       │              │
└──────┬───────┘       └──────┬───────┘
       │                      │
       └──────┬───────────────┘
              │ NCP Global Traffic Manager (가중치 라우팅)
              ▼
          사용자 트래픽
```

### 8.2 트래픽 이전 단계

| 일자 | 가중치 (VM : NKS) | 확인 |
|---|---|---|
| D+0 | 100 : 0 | NKS 헬스체크 통과, staging 테스트 완료 |
| D+1 | 90 : 10 | 에러율/latency 동등성 |
| D+3 | 50 : 50 | |
| D+7 | 10 : 90 | NKS autoscaling 동작 확인 |
| D+10 | 0 : 100 | VM 트래픽 제거 |
| D+17 | — | VM 환경 종료 (1주 보존 후 폐기) |

### 8.3 롤백 플랜

문제 발생 시 **즉시 GTM 가중치를 되돌린다** (VM : NKS = 100 : 0). 원인 분석 후 재시도.

**Rollback triggers (자동 알람):**
- 5xx > 1% (5분 rolling)
- p95 latency > 2x 평소
- DB 연결 실패율 > 0.5%
- 영수증 OCR 실패율 > 평소 + 5%p

---

## 9. 운영팀 온보딩 (6~7명 합류 시)

### 9.1 필수 역량 체크

| 역량 | 수준 | 학습 자료 |
|---|---|---|
| kubectl 기본 | `get/describe/logs/exec` 할 줄 앎 | 공식 튜토리얼 |
| Helm | `install/upgrade/rollback/values` | Helm docs |
| Argo CD | sync, history, rollback | Argo CD docs |
| Grafana | PromQL 기초, 대시보드 탐색 | 사내 런북 |
| 장애 대응 | 로그/메트릭/Exec 순서 | 사내 시뮬레이션 |

### 9.2 RBAC 역할 분배 (예시)

| 역할 | 권한 | 대상 |
|---|---|---|
| `cluster-admin` | 전 권한 | 2명 (Platform Lead) |
| `datapipeline-admin` | 앱 네임스페이스 전권 | 2명 |
| `datapipeline-editor` | kubectl read + argocd sync | 2명 |
| `datapipeline-viewer` | read only | 전원 |

### 9.3 런북 (`docs/runbooks/`) 최소 5종

1. `deploy_new_version.md` — 새 버전 배포 절차
2. `rollback.md` — 긴급 롤백
3. `pod_crashloop.md` — CrashLoopBackOff 대응
4. `db_connection_spike.md` — DB 커넥션 폭주
5. `ocr_budget_exceed.md` — CLOVA OCR 예산 초과 대응

### 9.4 훈련 (인계 시 1회 실시)

- **Game day** — 의도적 장애 주입(pod kill, node drain, DB 연결 차단)을 staging에서 수행, 복구까지 30분 내 통과 확인.

---

## 10. 비용 가이드 (참고)

| 리소스 | 월 예상 |
|---|---|
| NKS 노드 (s2-g3 x 3) | 약 30~40만 원 |
| NKS Control Plane | 매니지드 (무료 또는 저비용) |
| Cloud DB PG (prod+staging) | 약 40~60만 원 |
| Cloud DB Redis | 약 10만 원 |
| Object Storage (용량+트래픽) | 사용량 기반 (초기 5~10만 원) |
| Global Traffic Manager | 5만 원 내외 |
| **계** | **월 100~150만 원 수준** |

CLOVA OCR/임베딩 등 API 사용량은 별도.

---

## 11. 자주 발생하는 이관 함정

| 증상 | 원인 | 대책 |
|---|---|---|
| Pod OOMKilled | 로컬 테스트의 메모리 측정 안 함 | `kubectl top pod` 로 실측 후 limits 조정 |
| DB 커넥션 소진 | 복제 pod가 많은데 pool size 그대로 | `replicas × pool_size < max_connections` 확인 |
| Airflow DAG이 안 보임 | DAG 파일 볼륨 마운트 실패 | git-sync sidecar 또는 ConfigMap 확인 |
| External Secret 동기화 실패 | NCP Secret Manager 권한 | ServiceAccount IAM 연결 확인 |
| Ingress 404 | path/host 라우팅 미스 | `kubectl describe ingress` 로 backend 확인 |
| TLS 인증서 발급 실패 | DNS 미연결 | cert-manager `Order/Challenge` 상태 확인 |
| HPA가 스케일 안 함 | 메트릭 미노출 | `kubectl get hpa`, `kubectl top pod` |

---

## 12. 체크리스트 (Phase 4 이관 완료 기준)

- [ ] Terraform으로 VPC/NKS/DB/OS 전체 재생성 가능
- [ ] Argo CD staging/prod Application 동기화
- [ ] Helm chart로 전체 앱 배포
- [ ] Prometheus/Grafana/Loki 정상
- [ ] 5xx 알람 + OCR 예산 알람 동작
- [ ] 병행 운영 10일+ 후 VM 폐기 완료
- [ ] 운영팀 6~7명 kubectl/argocd 접근 확인
- [ ] Game day 1회 통과
- [ ] 런북 5종 이상
- [ ] 월 비용 모니터링 대시보드

---

## 13. Claude에게 이관 도움 요청 예시

```
"docs/ops/NKS_DEPLOYMENT.md 6.1 backend-deployment.yaml 을 우리 레포에 맞춰 실제 파일로 만들어줘.
파일 위치 infra/k8s/helm/datapipeline/templates/backend-deployment.yaml.
values.yaml 도 같이 만들고, 나머지는 다음 턴에 할게."

"infra/terraform/ncp/modules/nks 모듈을 만들어줘.
입력 변수는 vpc_id, subnet_id, node_count, node_spec.
출력은 cluster_uuid, kubeconfig_path."

"Argo CD App of Apps 패턴으로 root-app.yaml 만들고,
infra/k8s/argocd/apps/ 하위에 datapipeline-staging, datapipeline-prod 두 Application 생성해줘."
```
