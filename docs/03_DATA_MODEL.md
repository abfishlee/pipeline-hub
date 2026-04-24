# 03. 데이터 모델 (전체 DDL)

**이 문서는 단일 출처(Single Source of Truth).** DB 스키마 변경은 여기 먼저 반영하고 Alembic migration 파일 작성.

## 3.1 스키마 목록

```
ctl    : 시스템 설정, 소스/커넥터 정의, 사용자
raw    : 수집 원천 (메타데이터 + 파일 참조)
stg    : 표준화된 staging 데이터
wf     : Visual Pipeline 정의
run    : 실행 이력, outbox, processed_event
dq     : 데이터 품질 규칙/결과
mart   : 마스터/서비스용 분석 테이블
audit  : 접근/SQL 실행/다운로드 감사
```

확장:
```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;
```

## 3.2 ctl 스키마

```sql
CREATE SCHEMA IF NOT EXISTS ctl;

-- 사용자
CREATE TABLE ctl.app_user (
    user_id           BIGSERIAL PRIMARY KEY,
    login_id          TEXT NOT NULL UNIQUE,
    display_name      TEXT NOT NULL,
    email             TEXT UNIQUE,
    password_hash     TEXT NOT NULL,          -- Argon2id
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 역할 (RBAC)
CREATE TABLE ctl.role (
    role_id           BIGSERIAL PRIMARY KEY,
    role_code         TEXT NOT NULL UNIQUE,   -- ADMIN, OPERATOR, REVIEWER, APPROVER, VIEWER
    role_name         TEXT NOT NULL,
    description       TEXT
);

CREATE TABLE ctl.user_role (
    user_id           BIGINT NOT NULL REFERENCES ctl.app_user(user_id) ON DELETE CASCADE,
    role_id           BIGINT NOT NULL REFERENCES ctl.role(role_id)     ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- 데이터 소스
CREATE TABLE ctl.data_source (
    source_id         BIGSERIAL PRIMARY KEY,
    source_code       TEXT NOT NULL UNIQUE,
    source_name       TEXT NOT NULL,
    source_type       TEXT NOT NULL CHECK (
        source_type IN ('API','OCR','DB','CRAWLER','CROWD','RECEIPT','APP')
    ),
    retailer_id       BIGINT,                   -- mart.retailer_master 참조 (soft)
    owner_team        TEXT,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    config_json       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- API URL, 인증방식, 주기 등
    schedule_cron     TEXT,                     -- 정기 수집이면 cron
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 커넥터 정의 (DB-to-DB용)
CREATE TABLE ctl.connector (
    connector_id      BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
    connector_kind    TEXT NOT NULL CHECK (
        connector_kind IN ('PG','MYSQL','ORACLE','MSSQL','HTTP','S3')
    ),
    secret_ref        TEXT NOT NULL,            -- NCP Secret Manager key
    config_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- API Key (외부 소비자용, Phase 4)
CREATE TABLE ctl.api_key (
    api_key_id        BIGSERIAL PRIMARY KEY,
    key_prefix        TEXT NOT NULL UNIQUE,     -- 표시용 (풀 키는 해시만 저장)
    key_hash          TEXT NOT NULL,            -- Argon2id of full key
    client_name       TEXT NOT NULL,
    scope             TEXT[] NOT NULL DEFAULT '{}',
    rate_limit_per_min INT NOT NULL DEFAULT 60,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expired_at        TIMESTAMPTZ
);
```

## 3.3 raw 스키마

```sql
CREATE SCHEMA IF NOT EXISTS raw;

-- 모든 수집 원천의 공통 헤더
CREATE TABLE raw.raw_object (
    raw_object_id     BIGSERIAL,
    source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
    job_id            BIGINT,                   -- FK는 run.ingest_job 생성 후 add
    object_type       TEXT NOT NULL CHECK (
        object_type IN ('JSON','XML','CSV','HTML','PDF','IMAGE','DB_ROW','RECEIPT_IMAGE')
    ),
    object_uri        TEXT,                     -- Object Storage URI (nos://bucket/key)
    payload_json      JSONB,                    -- 작은 JSON은 인라인 저장 (<64KB 권장)
    content_hash      TEXT NOT NULL,            -- sha256
    idempotency_key   TEXT,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    partition_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    status            TEXT NOT NULL DEFAULT 'RECEIVED' CHECK (
        status IN ('RECEIVED','PROCESSED','FAILED','DISCARDED')
    ),
    PRIMARY KEY (raw_object_id, partition_date)
) PARTITION BY RANGE (partition_date);

-- 초기 파티션 (이후 월별 자동 생성 스크립트로 관리)
CREATE TABLE raw.raw_object_2026_04 PARTITION OF raw.raw_object
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE INDEX raw_object_source_received_idx
    ON raw.raw_object (source_id, received_at DESC);
CREATE INDEX raw_object_status_idx
    ON raw.raw_object (status) WHERE status IN ('RECEIVED','FAILED');
CREATE INDEX raw_object_payload_gin
    ON raw.raw_object USING gin (payload_json jsonb_path_ops);

-- 전역 content_hash 유니크 인덱스 (파티션 PK로 불가능한 제약을 보완)
CREATE TABLE raw.content_hash_index (
    content_hash      TEXT PRIMARY KEY,
    raw_object_id     BIGINT NOT NULL,
    partition_date    DATE NOT NULL,
    source_id         BIGINT NOT NULL,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX content_hash_source_idx ON raw.content_hash_index (source_id);

-- OCR 결과
CREATE TABLE raw.ocr_result (
    ocr_result_id     BIGSERIAL PRIMARY KEY,
    raw_object_id     BIGINT NOT NULL,
    partition_date    DATE NOT NULL,
    page_no           INTEGER,
    text_content      TEXT,
    confidence_score  NUMERIC(5,2),
    layout_json       JSONB,                    -- bounding boxes, line/word level
    engine_name       TEXT NOT NULL,            -- 'clova','upstage','tesseract'
    engine_version    TEXT,
    duration_ms       INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ocr_result_raw_idx
    ON raw.ocr_result (raw_object_id, partition_date);

-- 크롤링 원본 페이지
CREATE TABLE raw.raw_web_page (
    page_id           BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
    job_id            BIGINT,
    url               TEXT NOT NULL,
    http_status       INTEGER,
    html_object_uri   TEXT NOT NULL,            -- Object Storage 경로
    response_headers  JSONB,
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_hash      TEXT NOT NULL,
    parser_version    TEXT
);

CREATE INDEX raw_web_page_url_fetched_idx
    ON raw.raw_web_page (url, fetched_at DESC);

-- DB-to-DB 수집 스냅샷 메타
CREATE TABLE raw.db_snapshot (
    snapshot_id       BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
    job_id            BIGINT,
    table_name        TEXT NOT NULL,
    mode              TEXT NOT NULL CHECK (mode IN ('SNAPSHOT','INCREMENTAL','CDC')),
    row_count         BIGINT,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ,
    watermark         TEXT,                     -- updated_at/sequence 값
    status            TEXT NOT NULL DEFAULT 'RUNNING'
);
```

## 3.4 stg 스키마

```sql
CREATE SCHEMA IF NOT EXISTS stg;

-- 모든 도메인의 공통 표준 레코드 (JSONB body)
CREATE TABLE stg.standard_record (
    record_id         BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
    raw_object_id     BIGINT,
    raw_partition     DATE,                     -- raw_object와 함께 조인
    entity_type       TEXT NOT NULL,            -- 'PRODUCT','PRICE','RETAILER','SELLER'
    business_key      TEXT,
    record_json       JSONB NOT NULL,
    observed_at       TIMESTAMPTZ,              -- 가격 관찰 시각
    valid_from        TIMESTAMPTZ,
    valid_to          TIMESTAMPTZ,
    quality_score     NUMERIC(5,2),
    load_batch_id     BIGINT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX stg_standard_record_entity_bk
    ON stg.standard_record (entity_type, business_key);
CREATE INDEX stg_standard_record_source
    ON stg.standard_record (source_id, created_at DESC);

-- 가격 관찰 전용 staging (자주 쓰므로 별도 컬럼화)
CREATE TABLE stg.price_observation (
    obs_id            BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
    raw_object_id     BIGINT,
    raw_partition     DATE,
    retailer_code     TEXT,                     -- 유통사 코드
    seller_name       TEXT,
    store_name        TEXT,
    product_name_raw  TEXT NOT NULL,            -- 원본 상품명 (표준화 전)
    std_code          TEXT,                     -- 매핑된 표준코드 (nullable until standardized)
    std_confidence    NUMERIC(5,2),
    grade             TEXT,
    package_type      TEXT,
    sale_unit         TEXT,                     -- '1kg','박스','500g' 등
    weight_g          NUMERIC(12,2),
    brix              NUMERIC(5,2),
    price_krw         NUMERIC(14,2) NOT NULL,
    discount_price_krw NUMERIC(14,2),
    currency          TEXT NOT NULL DEFAULT 'KRW',
    observed_at       TIMESTAMPTZ NOT NULL,
    standardized_at   TIMESTAMPTZ,
    load_batch_id     BIGINT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX stg_price_obs_std_observed
    ON stg.price_observation (std_code, observed_at DESC);
CREATE INDEX stg_price_obs_retailer_observed
    ON stg.price_observation (retailer_code, observed_at DESC);
CREATE INDEX stg_price_obs_unstandardized
    ON stg.price_observation (source_id, created_at)
    WHERE std_code IS NULL;
```

## 3.5 mart 스키마 (서비스용)

```sql
CREATE SCHEMA IF NOT EXISTS mart;

-- 표준코드 (농림축산식품부/aT 기준 품목)
CREATE TABLE mart.standard_code (
    std_code          TEXT PRIMARY KEY,         -- 예: 'VEG-PARM-01' (과일/채소/축산 prefix)
    category_lv1      TEXT NOT NULL,            -- '채소','과일','축산','수산' 등
    category_lv2      TEXT,
    category_lv3      TEXT,
    item_name_ko      TEXT NOT NULL,            -- '참외'
    aliases           TEXT[] NOT NULL DEFAULT '{}',  -- ['참외','chamoe','golden melon']
    default_unit      TEXT,
    source_authority  TEXT,                     -- 'MAFRA','aT','INTERNAL'
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX mart_standard_code_item_trgm
    ON mart.standard_code USING gin (item_name_ko gin_trgm_ops);
CREATE INDEX mart_standard_code_aliases_gin
    ON mart.standard_code USING gin (aliases);

-- 유통사 마스터
CREATE TABLE mart.retailer_master (
    retailer_id       BIGSERIAL PRIMARY KEY,
    retailer_code     TEXT NOT NULL UNIQUE,     -- 내부 코드
    retailer_name     TEXT NOT NULL,
    retailer_type     TEXT NOT NULL CHECK (
        retailer_type IN ('MART','SSM','LOCAL','ONLINE','TRAD_MARKET','APP')
    ),
    business_no       TEXT,
    head_office_addr  TEXT,
    meta_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 판매자 마스터 (= 매장/점포/온라인 스토어)
CREATE TABLE mart.seller_master (
    seller_id         BIGSERIAL PRIMARY KEY,
    retailer_id       BIGINT REFERENCES mart.retailer_master(retailer_id),
    seller_code       TEXT NOT NULL,            -- retailer 내에서 unique
    seller_name       TEXT NOT NULL,
    channel           TEXT NOT NULL CHECK (channel IN ('OFFLINE','ONLINE')),
    region_sido       TEXT,
    region_sigungu    TEXT,
    address           TEXT,
    geo_point         POINT,
    meta_json         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (retailer_id, seller_code)
);

-- 상품 마스터 (표준코드에 묶인 canonical product)
CREATE TABLE mart.product_master (
    product_id        BIGSERIAL PRIMARY KEY,
    std_code          TEXT NOT NULL REFERENCES mart.standard_code(std_code),
    grade             TEXT,
    package_type      TEXT,
    sale_unit_norm    TEXT,                     -- 정규화 단위 '1kg','500g'
    weight_g          NUMERIC(12,2),
    canonical_name    TEXT NOT NULL,
    first_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    confidence_score  NUMERIC(5,2),
    UNIQUE (std_code, grade, package_type, sale_unit_norm, weight_g)
);

-- 원천 상품 ↔ 마스터 상품 매핑
CREATE TABLE mart.product_mapping (
    mapping_id        BIGSERIAL PRIMARY KEY,
    retailer_id       BIGINT NOT NULL REFERENCES mart.retailer_master(retailer_id),
    retailer_product_code TEXT,                 -- 유통사 내부 코드 (있으면)
    raw_product_name  TEXT NOT NULL,
    product_id        BIGINT NOT NULL REFERENCES mart.product_master(product_id),
    match_method      TEXT NOT NULL CHECK (
        match_method IN ('EMBEDDING','RULE','HUMAN','ALIAS')
    ),
    confidence_score  NUMERIC(5,2),
    verified_by       BIGINT REFERENCES ctl.app_user(user_id),
    verified_at       TIMESTAMPTZ,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX mart_product_mapping_lookup
    ON mart.product_mapping (retailer_id, retailer_product_code);
CREATE INDEX mart_product_mapping_name_trgm
    ON mart.product_mapping USING gin (raw_product_name gin_trgm_ops);

-- 가격 이력 (서비스의 핵심 팩트 테이블)
CREATE TABLE mart.price_fact (
    price_id          BIGSERIAL,
    product_id        BIGINT NOT NULL REFERENCES mart.product_master(product_id),
    seller_id         BIGINT NOT NULL REFERENCES mart.seller_master(seller_id),
    observed_at       TIMESTAMPTZ NOT NULL,
    price_krw         NUMERIC(14,2) NOT NULL,
    discount_price_krw NUMERIC(14,2),
    unit_price_per_kg NUMERIC(14,2),            -- 정규화 단가 (kg당)
    source_id         BIGINT NOT NULL,
    raw_object_id     BIGINT,
    partition_date    DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (price_id, partition_date)
) PARTITION BY RANGE (partition_date);

CREATE TABLE mart.price_fact_2026_04 PARTITION OF mart.price_fact
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE INDEX mart_price_fact_product_time
    ON mart.price_fact (product_id, observed_at DESC);
CREATE INDEX mart_price_fact_seller_time
    ON mart.price_fact (seller_id, observed_at DESC);
CREATE INDEX mart_price_fact_observed_brin
    ON mart.price_fact USING BRIN (observed_at);

-- 일별 가격 집계 (대시보드/API 빠른 조회용)
CREATE TABLE mart.price_daily_agg (
    agg_date          DATE NOT NULL,
    std_code          TEXT NOT NULL REFERENCES mart.standard_code(std_code),
    retailer_id       BIGINT,
    region_sido       TEXT,
    min_price_krw     NUMERIC(14,2),
    avg_price_krw     NUMERIC(14,2),
    max_price_krw     NUMERIC(14,2),
    median_price_krw  NUMERIC(14,2),
    obs_count         INTEGER NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agg_date, std_code, retailer_id, region_sido)
);

-- 마스터 엔티티 이력 (SCD Type 2)
CREATE TABLE mart.master_entity_history (
    history_id        BIGSERIAL PRIMARY KEY,
    entity_type       TEXT NOT NULL,            -- 'PRODUCT','RETAILER','SELLER'
    entity_id         BIGINT NOT NULL,
    canonical_json    JSONB NOT NULL,
    valid_from        TIMESTAMPTZ NOT NULL,
    valid_to          TIMESTAMPTZ,
    is_current        BOOLEAN NOT NULL DEFAULT TRUE,
    changed_reason    TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX mart_master_history_current
    ON mart.master_entity_history (entity_type, entity_id)
    WHERE is_current = TRUE;
```

## 3.6 wf 스키마

```sql
CREATE SCHEMA IF NOT EXISTS wf;

CREATE TABLE wf.pipeline (
    pipeline_id       BIGSERIAL PRIMARY KEY,
    pipeline_name     TEXT NOT NULL,
    description       TEXT,
    version_no        INTEGER NOT NULL DEFAULT 1,
    status            TEXT NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT','PUBLISHED','ARCHIVED')
    ),
    schedule_cron     TEXT,
    owner_user_id     BIGINT REFERENCES ctl.app_user(user_id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (pipeline_name, version_no)
);

CREATE TABLE wf.pipeline_node (
    node_id           BIGSERIAL PRIMARY KEY,
    pipeline_id       BIGINT NOT NULL REFERENCES wf.pipeline(pipeline_id) ON DELETE CASCADE,
    node_key          TEXT NOT NULL,
    node_type         TEXT NOT NULL,            -- SOURCE_API, OCR, SQL_TRANSFORM, ...
    node_name         TEXT NOT NULL,
    position_x        NUMERIC,
    position_y        NUMERIC,
    config_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (pipeline_id, node_key)
);

CREATE TABLE wf.pipeline_edge (
    edge_id           BIGSERIAL PRIMARY KEY,
    pipeline_id       BIGINT NOT NULL REFERENCES wf.pipeline(pipeline_id) ON DELETE CASCADE,
    from_node_key     TEXT NOT NULL,
    to_node_key       TEXT NOT NULL,
    condition_expr    TEXT,
    config_json       JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX wf_pipeline_edge_pip ON wf.pipeline_edge (pipeline_id);
```

## 3.7 run 스키마

```sql
CREATE SCHEMA IF NOT EXISTS run;

-- 수집 작업 이력
CREATE TABLE run.ingest_job (
    job_id            BIGSERIAL PRIMARY KEY,
    source_id         BIGINT NOT NULL REFERENCES ctl.data_source(source_id),
    job_type          TEXT NOT NULL CHECK (
        job_type IN ('ON_DEMAND','SCHEDULED','RETRY','BACKFILL')
    ),
    status            TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED')
    ),
    requested_by      BIGINT REFERENCES ctl.app_user(user_id),
    parameters        JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    input_count       BIGINT DEFAULT 0,
    output_count      BIGINT DEFAULT 0,
    error_count       BIGINT DEFAULT 0,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX run_ingest_job_source_created
    ON run.ingest_job (source_id, created_at DESC);
CREATE INDEX run_ingest_job_status
    ON run.ingest_job (status) WHERE status IN ('PENDING','RUNNING','FAILED');

-- 파이프라인 실행
CREATE TABLE run.pipeline_run (
    pipeline_run_id   BIGSERIAL PRIMARY KEY,
    pipeline_id       BIGINT NOT NULL REFERENCES wf.pipeline(pipeline_id),
    version_no        INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','RUNNING','SUCCESS','FAILED','CANCELLED','ON_HOLD')
    ),
    triggered_by      BIGINT REFERENCES ctl.app_user(user_id),
    trigger_kind      TEXT NOT NULL CHECK (trigger_kind IN ('MANUAL','SCHEDULED','EVENT')),
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX run_pipeline_run_pip_created
    ON run.pipeline_run (pipeline_id, created_at DESC);

-- 노드 실행
CREATE TABLE run.node_run (
    node_run_id       BIGSERIAL PRIMARY KEY,
    pipeline_run_id   BIGINT NOT NULL REFERENCES run.pipeline_run(pipeline_run_id) ON DELETE CASCADE,
    node_key          TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','READY','RUNNING','SUCCESS','FAILED','SKIPPED','RETRYING','CANCELLED')
    ),
    attempt_no        INT NOT NULL DEFAULT 0,
    input_count       BIGINT DEFAULT 0,
    output_count      BIGINT DEFAULT 0,
    error_count       BIGINT DEFAULT 0,
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    error_message     TEXT,
    metrics_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (pipeline_run_id, node_key)
);

CREATE INDEX run_node_run_status
    ON run.node_run (status) WHERE status IN ('RUNNING','FAILED','RETRYING');

-- Outbox
CREATE TABLE run.event_outbox (
    event_id          BIGSERIAL PRIMARY KEY,
    aggregate_type    TEXT NOT NULL,
    aggregate_id      TEXT NOT NULL,
    event_type        TEXT NOT NULL,
    payload_json      JSONB NOT NULL,
    status            TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING','PUBLISHED','FAILED')
    ),
    attempt_no        INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at      TIMESTAMPTZ,
    last_error        TEXT
);

CREATE INDEX run_event_outbox_pending
    ON run.event_outbox (created_at) WHERE status = 'PENDING';

-- Idempotent consumer marker
CREATE TABLE run.processed_event (
    event_id          TEXT PRIMARY KEY,
    consumer_name     TEXT NOT NULL,
    processed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX run_processed_event_consumer
    ON run.processed_event (consumer_name, processed_at);

-- Dead Letter
CREATE TABLE run.dead_letter (
    dl_id             BIGSERIAL PRIMARY KEY,
    origin            TEXT NOT NULL,            -- 'ocr_worker','transform_worker' 등
    payload_json      JSONB NOT NULL,
    error_message     TEXT,
    stack_trace       TEXT,
    failed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    replayed_at       TIMESTAMPTZ,
    replayed_by       BIGINT REFERENCES ctl.app_user(user_id)
);
```

## 3.8 dq 스키마

```sql
CREATE SCHEMA IF NOT EXISTS dq;

CREATE TABLE dq.quality_rule (
    rule_id           BIGSERIAL PRIMARY KEY,
    rule_name         TEXT NOT NULL UNIQUE,
    target_schema     TEXT NOT NULL,
    target_table      TEXT NOT NULL,
    rule_type         TEXT NOT NULL CHECK (
        rule_type IN ('NOT_NULL','FORMAT','RANGE','REFERENCE','UNIQUE','CONSISTENCY','DISTRIBUTION','OCR_CONF')
    ),
    rule_sql          TEXT NOT NULL,            -- 실패 row를 반환하는 SELECT
    severity          TEXT NOT NULL CHECK (severity IN ('INFO','WARN','ERROR')),
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE dq.quality_result (
    result_id         BIGSERIAL PRIMARY KEY,
    rule_id           BIGINT NOT NULL REFERENCES dq.quality_rule(rule_id),
    pipeline_run_id   BIGINT REFERENCES run.pipeline_run(pipeline_run_id),
    node_run_id       BIGINT REFERENCES run.node_run(node_run_id),
    status            TEXT NOT NULL CHECK (status IN ('PASS','FAIL','ERROR')),
    failed_count      BIGINT DEFAULT 0,
    sample_json       JSONB,                    -- 실패 예시 상위 10건
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX dq_quality_result_rule_time
    ON dq.quality_result (rule_id, checked_at DESC);
CREATE INDEX dq_quality_result_run
    ON dq.quality_result (pipeline_run_id);
```

## 3.9 audit 스키마

```sql
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE audit.access_log (
    log_id            BIGSERIAL PRIMARY KEY,
    user_id           BIGINT REFERENCES ctl.app_user(user_id),
    api_key_id        BIGINT REFERENCES ctl.api_key(api_key_id),
    method            TEXT NOT NULL,
    path              TEXT NOT NULL,
    status_code       INT,
    ip                INET,
    user_agent        TEXT,
    duration_ms       INT,
    request_id        TEXT,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (occurred_at);

CREATE TABLE audit.access_log_2026_04 PARTITION OF audit.access_log
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

CREATE INDEX audit_access_log_user_time
    ON audit.access_log (user_id, occurred_at DESC);

CREATE TABLE audit.sql_execution_log (
    sql_log_id        BIGSERIAL PRIMARY KEY,
    user_id           BIGINT NOT NULL REFERENCES ctl.app_user(user_id),
    sql_text          TEXT NOT NULL,
    sql_hash          TEXT NOT NULL,
    execution_kind    TEXT NOT NULL CHECK (execution_kind IN ('PREVIEW','SANDBOX','APPROVED','SCHEDULED')),
    target_schema     TEXT,
    approved_by       BIGINT REFERENCES ctl.app_user(user_id),
    approved_at       TIMESTAMPTZ,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    row_count         BIGINT,
    status            TEXT NOT NULL CHECK (status IN ('SUCCESS','FAILED','BLOCKED','PENDING_APPROVAL')),
    error_message     TEXT
);

CREATE INDEX audit_sql_log_user_time
    ON audit.sql_execution_log (user_id, started_at DESC);

CREATE TABLE audit.download_log (
    download_id       BIGSERIAL PRIMARY KEY,
    user_id           BIGINT REFERENCES ctl.app_user(user_id),
    api_key_id        BIGINT REFERENCES ctl.api_key(api_key_id),
    resource_kind     TEXT NOT NULL,            -- 'RAW_OBJECT','PRICE_EXPORT','OCR_IMAGE'
    resource_ref      TEXT NOT NULL,
    byte_count        BIGINT,
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 3.10 Crowd 관련 테이블 (wf/run 공통)

```sql
CREATE TABLE wf.crowd_task (
    crowd_task_id     BIGSERIAL PRIMARY KEY,
    task_kind         TEXT NOT NULL CHECK (
        task_kind IN ('OCR_REVIEW','PRODUCT_MATCHING','RECEIPT_VALIDATION','ANOMALY_CHECK')
    ),
    payload_json      JSONB NOT NULL,           -- 작업에 필요한 데이터 참조
    source_raw_object_id BIGINT,
    raw_partition     DATE,
    status            TEXT NOT NULL DEFAULT 'OPEN' CHECK (
        status IN ('OPEN','ASSIGNED','IN_REVIEW','CONFLICT','APPROVED','REJECTED','CLOSED')
    ),
    priority          INT NOT NULL DEFAULT 5,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at         TIMESTAMPTZ
);

CREATE TABLE wf.crowd_assignment (
    assignment_id     BIGSERIAL PRIMARY KEY,
    crowd_task_id     BIGINT NOT NULL REFERENCES wf.crowd_task(crowd_task_id) ON DELETE CASCADE,
    reviewer_user_id  BIGINT NOT NULL REFERENCES ctl.app_user(user_id),
    assigned_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at      TIMESTAMPTZ,
    result_json       JSONB,
    status            TEXT NOT NULL DEFAULT 'ASSIGNED' CHECK (
        status IN ('ASSIGNED','SUBMITTED','WITHDRAWN')
    )
);
```

## 3.11 권한/역할 seed 데이터

```sql
INSERT INTO ctl.role (role_code, role_name, description) VALUES
  ('ADMIN',    '관리자',        '전 권한'),
  ('OPERATOR', '운영자',        '수집/파이프라인 운영'),
  ('REVIEWER', '검수자',        '크라우드 검수 전용'),
  ('APPROVER', '승인자',        'SQL/Mart 반영 승인'),
  ('VIEWER',   '조회자',        '읽기 전용')
ON CONFLICT DO NOTHING;
```

## 3.12 인덱스 전략 요약

| 테이블 | 전략 |
|---|---|
| `raw.raw_object` | partition + source/received 인덱스, payload gin(jsonb_path_ops) |
| `mart.price_fact` | partition + product/seller + observed BRIN (append-heavy) |
| `mart.standard_code` | trigram gin for fuzzy search, aliases gin |
| `mart.product_mapping` | trigram gin on raw_product_name |
| `run.event_outbox` | partial index on status='PENDING' |
| `run.node_run` | partial index on 활성 상태 |
| `audit.access_log` | partition + user/time |

## 3.13 파티션 관리 규칙

- **월 단위 파티션** 테이블: `raw.raw_object`, `mart.price_fact`, `audit.access_log`.
- 매월 1일 03:00에 다음 달 파티션 자동 생성 (Phase 2 스케줄러 작업).
- 13개월 이상 지난 `raw.raw_object` 파티션은 Object Storage 아카이브 후 DETACH.

## 3.14 변경 절차

1. 이 문서 먼저 수정 (PR 포함).
2. `migrations/versions/` 에 Alembic revision 작성.
3. 로컬 migration up/down 양방향 테스트.
4. dev 환경 migration 적용 후 회귀 테스트.
5. prod 배포.
