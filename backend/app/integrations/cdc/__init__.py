"""CDC integrations (Phase 4.2.3).

경로 A — wal2json + logical replication slot 직접 구독.
경로 B (Kafka + Debezium) 는 ADR-0013 회수 조건 만족 시 추가.
"""

from __future__ import annotations
