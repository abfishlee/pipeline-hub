-- Phase 2.2.3 — Airflow metadata 전용 데이터베이스 생성.
-- 메인 애플리케이션 DB (`datapipeline`) 와 동일 PostgreSQL 클러스터, 다른 DB.
-- postgres 컨테이너 첫 기동 시 1회만 실행 (POSTGRES_DB 가 만들어진 후).
--
-- 운영(NKS) 에서는 Cloud DB for PostgreSQL 에 동일 스크립트로 사전 프로비저닝.

SELECT 'CREATE DATABASE airflow OWNER app'
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'airflow')\gexec

GRANT ALL PRIVILEGES ON DATABASE airflow TO app;
