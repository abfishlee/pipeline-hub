-- Phase 4.2.3 — CDC slot/publication 1회 셋업 (superuser 권한 필요).
-- 사용법:
--   psql "$DATABASE_URL" \
--        -v slot_name='dp_cdc_<source>' \
--        -v publication_name='dp_cdc_<source>' \
--        -v table_list='public.products,public.prices' \
--        -f scripts/setup_cdc_slot.sql
--
-- 사전 조건 (postgresql.conf):
--   wal_level = logical
--   max_replication_slots >= 4
--   max_wal_senders >= 4
--   shared_preload_libraries 에 'wal2json' (확장 미설치 시 apt install postgresql-16-wal2json)
--
-- 본 스크립트는 idempotent — 이미 존재하면 NOTICE 만 출력하고 통과.

\if :{?slot_name}
\else
    \echo 'ERROR: -v slot_name 필수'
    \quit
\endif
\if :{?publication_name}
\else
    \echo 'ERROR: -v publication_name 필수'
    \quit
\endif
\if :{?table_list}
\else
    \echo 'ERROR: -v table_list 필수 (콤마 구분)'
    \quit
\endif

-- 1) PUBLICATION (이미 있으면 그대로 둠).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = :'publication_name') THEN
        EXECUTE format('CREATE PUBLICATION %I FOR TABLE %s',
                       :'publication_name',
                       :'table_list');
        RAISE NOTICE 'created publication %', :'publication_name';
    ELSE
        RAISE NOTICE 'publication % already exists, skipping', :'publication_name';
    END IF;
END
$$;

-- 2) Logical replication slot (wal2json plugin).
DO $$
DECLARE
    existing TEXT;
BEGIN
    SELECT slot_name INTO existing
      FROM pg_replication_slots
     WHERE slot_name = :'slot_name';
    IF existing IS NULL THEN
        PERFORM pg_create_logical_replication_slot(:'slot_name', 'wal2json');
        RAISE NOTICE 'created slot %', :'slot_name';
    ELSE
        RAISE NOTICE 'slot % already exists, skipping', :'slot_name';
    END IF;
END
$$;

-- 3) 결과 출력.
SELECT slot_name, plugin, slot_type, active, restart_lsn, confirmed_flush_lsn
  FROM pg_replication_slots
 WHERE slot_name = :'slot_name';

SELECT pubname, puballtables
  FROM pg_publication
 WHERE pubname = :'publication_name';
