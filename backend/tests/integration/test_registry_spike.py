"""Phase 5.2.1a Spike — Hybrid Resource Registry 통합 테스트.

검증:
  1. register_resource → reflect → list_columns
  2. INSERT (sensor_v1) → PK 반환
  3. SELECT WHERE
  4. UPDATE / DELETE
  5. JOIN (sensor + reading)
  6. vector(512) INSERT (CAST AS vector)
  7. vector(1024) INSERT (다른 차원 같은 도메인)
  8. v1 ORM 회귀 — DataSource 그대로 import + query 가능
  9. Option A (동적 ORM) 의 한계 시연 — registry conflict 발생

본 spike 는 ADR-0017 의 *근거 코드* — production 비포함.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.db.sync_session import dispose_sync_engine, get_sync_sessionmaker
from app.experimental.registry_spike import (
    HybridResourceRegistry,
    option_a_dynamic_orm_class,
    sync_dsn_from_settings,
)
from app.models.ctl import DataSource


@pytest.fixture
def registry() -> Iterator[HybridResourceRegistry]:
    reg = HybridResourceRegistry.from_dsn(sync_dsn_from_settings())
    yield reg
    reg.engine.dispose()


@pytest.fixture
def cleanup_spike() -> Iterator[None]:
    yield
    sm = get_sync_sessionmaker()
    with sm() as session:
        # 모든 spike row 정리 — schema 자체는 downgrade 시 정리.
        session.execute(text("TRUNCATE iot_spike_mart.embedding_512 CASCADE;"))
        session.execute(text("TRUNCATE iot_spike_mart.embedding_1024 CASCADE;"))
        session.execute(text("TRUNCATE iot_spike_mart.reading_v1 CASCADE;"))
        session.execute(text("TRUNCATE iot_spike_mart.sensor_v1 RESTART IDENTITY CASCADE;"))
        session.commit()
    dispose_sync_engine()


# ---------------------------------------------------------------------------
# 1. register + reflect + list_columns
# ---------------------------------------------------------------------------
def test_register_and_reflect(
    registry: HybridResourceRegistry, cleanup_spike: None
) -> None:
    registry.register_resource(
        domain_code="iot_spike",
        resource_code="sensor",
        schema_name="iot_spike_mart",
        table_name="sensor_v1",
    )
    cols = registry.list_columns(domain_code="iot_spike", resource_code="sensor")
    names = [c[0] for c in cols]
    assert "sensor_id" in names
    assert "device_model_id" in names
    assert "unit" in names


# ---------------------------------------------------------------------------
# 2. INSERT + PK 반환
# ---------------------------------------------------------------------------
def test_insert_returns_pk(
    registry: HybridResourceRegistry, cleanup_spike: None
) -> None:
    registry.register_resource(
        domain_code="iot_spike", resource_code="sensor",
        schema_name="iot_spike_mart", table_name="sensor_v1",
    )
    sid = registry.insert(
        "iot_spike",
        "sensor",
        {"device_model_id": "DHT22", "location": "room-1", "unit": "°C"},
    )
    assert sid > 0


# ---------------------------------------------------------------------------
# 3. SELECT WHERE
# ---------------------------------------------------------------------------
def test_select_with_where(
    registry: HybridResourceRegistry, cleanup_spike: None
) -> None:
    registry.register_resource(
        domain_code="iot_spike", resource_code="sensor",
        schema_name="iot_spike_mart", table_name="sensor_v1",
    )
    suffix = secrets.token_hex(3)
    registry.insert(
        "iot_spike", "sensor",
        {"device_model_id": f"DHT22-{suffix}", "location": "room-A", "unit": "°C"},
    )
    registry.insert(
        "iot_spike", "sensor",
        {"device_model_id": f"BMP280-{suffix}", "location": "room-B", "unit": "hPa"},
    )
    rows = registry.select(
        "iot_spike", "sensor", where={"device_model_id": f"DHT22-{suffix}"}
    )
    assert len(rows) == 1
    assert rows[0]["unit"] == "°C"


# ---------------------------------------------------------------------------
# 4. UPDATE / DELETE
# ---------------------------------------------------------------------------
def test_update_and_delete(
    registry: HybridResourceRegistry, cleanup_spike: None
) -> None:
    registry.register_resource(
        domain_code="iot_spike", resource_code="sensor",
        schema_name="iot_spike_mart", table_name="sensor_v1",
    )
    suffix = secrets.token_hex(3)
    sid = registry.insert(
        "iot_spike", "sensor",
        {"device_model_id": f"X-{suffix}", "location": "x", "unit": "K"},
    )

    # UPDATE
    n_updated = registry.update(
        "iot_spike", "sensor", where={"sensor_id": sid}, values={"location": "y"}
    )
    assert n_updated == 1
    rows = registry.select("iot_spike", "sensor", where={"sensor_id": sid})
    assert rows[0]["location"] == "y"

    # DELETE
    n_deleted = registry.delete_(
        "iot_spike", "sensor", where={"sensor_id": sid}
    )
    assert n_deleted == 1
    rows = registry.select("iot_spike", "sensor", where={"sensor_id": sid})
    assert rows == []


# ---------------------------------------------------------------------------
# 5. JOIN (sensor + reading)
# ---------------------------------------------------------------------------
def test_join_sensor_reading(
    registry: HybridResourceRegistry, cleanup_spike: None
) -> None:
    from datetime import UTC, datetime

    registry.register_resource(
        domain_code="iot_spike", resource_code="sensor",
        schema_name="iot_spike_mart", table_name="sensor_v1",
    )
    registry.register_resource(
        domain_code="iot_spike", resource_code="reading",
        schema_name="iot_spike_mart", table_name="reading_v1",
    )
    sid = registry.insert(
        "iot_spike", "sensor",
        {"device_model_id": "DHT22-J", "location": "join-test", "unit": "°C"},
    )
    for v in (21.5, 22.1, 23.0):
        registry.insert(
            "iot_spike", "reading",
            {
                "sensor_id": sid,
                "observed_at": datetime.now(UTC),
                "value": v,
                "quality_score": 99.0,
            },
        )
    rows = registry.join_select(
        left=("iot_spike", "sensor"),
        right=("iot_spike", "reading"),
        on=("sensor_id", "sensor_id"),
        where={"location": "join-test"},
    )
    assert len(rows) == 3
    # JOIN 결과에 sensor + reading 양쪽 컬럼 포함.
    assert all("device_model_id" in r and "value" in r for r in rows)


# ---------------------------------------------------------------------------
# 6 + 7. vector 차원 동적 — 같은 도메인에 512 / 1024 공존
# ---------------------------------------------------------------------------
def test_vector_two_dimensions_same_domain(
    registry: HybridResourceRegistry, cleanup_spike: None
) -> None:
    # 두 차원 등록.
    registry.register_resource(
        domain_code="iot_spike", resource_code="sensor",
        schema_name="iot_spike_mart", table_name="sensor_v1",
    )
    registry.register_resource(
        domain_code="iot_spike", resource_code="emb_512",
        schema_name="iot_spike_mart", table_name="embedding_512",
    )
    registry.register_resource(
        domain_code="iot_spike", resource_code="emb_1024",
        schema_name="iot_spike_mart", table_name="embedding_1024",
    )

    sid = registry.insert(
        "iot_spike", "sensor",
        {"device_model_id": "VEC", "location": "vec", "unit": "°C"},
    )

    # 차원 검증.
    assert registry.vector_dimension_of("spike-512") == 512
    assert registry.vector_dimension_of("spike-1024") == 1024

    # 두 차원 INSERT.
    registry.vector_insert(
        "iot_spike", "emb_512",
        pk_column="sensor_id", pk_value=sid,
        embedding=[0.1] * 512, model_name="spike-512",
    )
    registry.vector_insert(
        "iot_spike", "emb_1024",
        pk_column="sensor_id", pk_value=sid,
        embedding=[0.2] * 1024, model_name="spike-1024",
    )

    # 양쪽 모두 1 row 씩 적재.
    rows512 = registry.select("iot_spike", "emb_512", where={"sensor_id": sid})
    rows1024 = registry.select("iot_spike", "emb_1024", where={"sensor_id": sid})
    assert len(rows512) == 1
    assert len(rows1024) == 1


# ---------------------------------------------------------------------------
# 8. v1 ORM 회귀 — DataSource 가 spike 영향 0
# ---------------------------------------------------------------------------
def test_v1_orm_unaffected_by_registry() -> None:
    sm = get_sync_sessionmaker()
    with sm() as session:
        # spike 가 v1 ORM 의 declarative registry 를 깨뜨리지 않음을 검증.
        ds = DataSource(
            source_code=f"IT_SPIKE_REGRESS_{secrets.token_hex(3).upper()}",
            source_name="spike regression",
            source_type="API",
            is_active=True,
            config_json={},
        )
        session.add(ds)
        session.flush()
        assert ds.source_id > 0
        assert ds.cdc_enabled is False
        session.rollback()


# ---------------------------------------------------------------------------
# 9. Option A (동적 ORM) 의 *한 부분* 시연 — type() 으로 클래스 생성 가능
#    (단, registry conflict 가 발생하므로 production 사용 X)
# ---------------------------------------------------------------------------
def test_option_a_dynamic_orm_class_creation_works_but_isolated() -> None:
    """Option A 가 *기술적으로 가능* 함을 보임 — 그러나 한계 (registry conflict 등)
    때문에 채택하지 않음을 ADR-0017 에 기록."""
    cls1 = option_a_dynamic_orm_class(
        schema_name="iot_spike_mart",
        table_name="sensor_v1",
        columns=[("device_model_id", str), ("unit", str)],
    )
    assert cls1.__tablename__ == "sensor_v1"
    # 같은 schema/table 두 번 생성 → 별도 Base 라도 *글로벌 metadata* 에 같은 키가
    # 있으면 SQLAlchemy 가 reuse. extend_existing 으로 해결되지만 mypy/IDE 무력은
    # 본 PoC 의 한계 — ADR-0017 § 핵심 결정 1 참고.
    cls2 = option_a_dynamic_orm_class(
        schema_name="iot_spike_mart",
        table_name="sensor_v1",
        columns=[("device_model_id", str), ("unit", str)],
    )
    assert cls2.__tablename__ == "sensor_v1"
    # 두 클래스가 *별도 Base* 라 동일 객체 X (= mapping registry 분리됨).
    assert cls1 is not cls2
