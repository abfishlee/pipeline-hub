"""Phase 5.2.1a Spike — Hybrid Resource Registry PoC.

세 가지 옵션 비교:
  A) SQLAlchemy ORM 동적 클래스 생성 (`type()` declarative)
  B) SQLAlchemy Core + reflected Table
  C) Hybrid — v1 정적 ORM 유지 + v2 generic = Core + reflected Table  ★ 채택 후보

본 모듈은 *세 옵션 모두* 의 *최소 동작 코드* 를 제공해서 ADR-0017 의 비교 근거가
실제로 *돌아가는 코드* 임을 입증.

사용 예 (Hybrid, 추천):

    >>> reg = HybridResourceRegistry.from_dsn(SYNC_DSN)
    >>> reg.register_resource(
    ...     domain_code="iot_spike",
    ...     resource_code="sensor",
    ...     schema_name="iot_spike_mart",
    ...     table_name="sensor_v1",
    ... )
    >>> reg.insert("iot_spike", "sensor", {"device_model_id": "DHT22", "unit": "°C"})
    >>> rows = reg.select("iot_spike", "sensor", where={"device_model_id": "DHT22"})

ORM 호환 유지:

    >>> # v1 정적 ORM 은 그대로 import/사용 가능 — Hybrid 의 핵심.
    >>> from app.models.ctl import DataSource
    >>> assert hasattr(DataSource, "__tablename__")

본 PoC 는 production 코드에서 import 하지 않는다. ADR-0017 채택 후 본 모듈의 일부가
`backend/app/domain/registry.py` 로 이전된다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from sqlalchemy import (
    MetaData,
    Table,
    create_engine,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine, Row

logger = logging.getLogger(__name__)


# ===========================================================================
# 옵션 A — SQLAlchemy ORM 동적 클래스 생성
# ===========================================================================
def option_a_dynamic_orm_class(
    *,
    schema_name: str,
    table_name: str,
    columns: list[tuple[str, type]],
) -> type:
    """`type()` 으로 동적 declarative class 생성.

    한계 (실측):
      - Mapped[T] type hint 가 *런타임* 만 동작 — mypy 가 추론 못 함.
      - 같은 (schema, table) 에 대해 두 번 생성 시 SQLAlchemy registry conflict
        ("class is already mapped").
      - Alembic autogenerate 는 *Base.metadata 가 클래스 임포트 시점에 모든 테이블 알고
        있어야* 함 — 동적 생성은 import 시점 결정 불가.
    """
    from sqlalchemy import BigInteger, Column, Integer, Numeric, Text
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()  # 매번 새 base — registry conflict 회피.

    type_map: dict[type, Any] = {
        int: BigInteger,
        str: Text,
        float: Numeric(14, 4),
    }
    # 주의: dict key 가 `__xxx__` (dunder) 면 declarative 가 metadata 키로 인식 →
    # primary key 미감지 에러. 일반 이름 (`_dyn_pk`) 사용.
    pk_col = Column("_dyn_pk", Integer, primary_key=True, autoincrement=True)
    extra_cols: list[tuple[str, Any]] = []
    for name, py_type in columns:
        sa_type = type_map.get(py_type, Text)
        extra_cols.append((name, Column(name, sa_type, nullable=True)))

    cls_dict: dict[str, Any] = {
        "__tablename__": table_name,
        "__table_args__": {"schema": schema_name, "extend_existing": True},
        "_dyn_pk": pk_col,
    }
    for name, col in extra_cols:
        cls_dict[name] = col

    cls = type(
        f"{schema_name}_{table_name}_DynamicORM",
        (Base,),
        cls_dict,
    )
    return cls


# ===========================================================================
# 옵션 B — SQLAlchemy Core + reflected Table
# ===========================================================================
@dataclass(slots=True)
class CoreOnlyRegistry:
    """모든 도메인을 Core + reflection 으로만 처리.

    한계:
      - v1 의 정적 ORM (DataSource, ProductMaster 등) 까지도 reflection 으로 다루어야
        해서 *기존 v1 코드 변경 폭 큼*.
      - lazy loading / relationship eager 가 없음 — 운영 화면의 N+1 query 문제 재현
        가능성.
    """

    engine: Engine
    metadata: MetaData = field(default_factory=MetaData)
    _tables: dict[tuple[str, str], Table] = field(default_factory=dict)

    @classmethod
    def from_dsn(cls, dsn: str) -> CoreOnlyRegistry:
        return cls(engine=create_engine(dsn))

    def reflect(self, *, schema_name: str, table_name: str) -> Table:
        key = (schema_name, table_name)
        if key not in self._tables:
            tbl = Table(
                table_name,
                self.metadata,
                schema=schema_name,
                autoload_with=self.engine,
            )
            self._tables[key] = tbl
        return self._tables[key]


# ===========================================================================
# 옵션 C — Hybrid (★ 채택 후보)
# ===========================================================================
@dataclass(slots=True, frozen=True)
class ResourceRef:
    """generic resource 1건의 식별자."""

    domain_code: str
    resource_code: str
    schema_name: str
    table_name: str

    @property
    def fqn(self) -> tuple[str, str]:
        return (self.schema_name, self.table_name)


@dataclass(slots=True)
class HybridResourceRegistry:
    """v1 ORM 은 그대로 두고 v2 generic resource 는 Core + reflected Table 로 처리.

    철학:
      - v1 의 정적 도메인 (agri = 농축산물) 은 ORM 모델 그대로 — typed Mapped 의
        장점 유지.
      - v2 의 generic resource (iot/pos/pharma 등) 는 *yaml 등록* 후 Core + reflection
        으로 처리. ORM 클래스 동적 생성 X (registry conflict / mypy 회피).
      - 도메인별 vector 테이블은 차원이 다르더라도 Core 로는 *컬럼 메타* 만 알면 충분.

    핵심 메서드:
      register_resource → reflect → query (select / insert / update / delete / vector_search)
    """

    engine: Engine
    metadata: MetaData = field(default_factory=MetaData)
    _resources: dict[tuple[str, str], ResourceRef] = field(default_factory=dict)
    _tables: dict[tuple[str, str], Table] = field(default_factory=dict)

    # 기본 차원 매핑 — 임베딩 모델 → 차원.
    EMBEDDING_DIMENSIONS: ClassVar[dict[str, int]] = {
        "spike-512": 512,
        "spike-1024": 1024,
        "hyperclova": 1536,
        "openai-ada-002": 1536,
        "openai-3-large": 3072,
    }

    @classmethod
    def from_dsn(cls, dsn: str) -> HybridResourceRegistry:
        return cls(engine=create_engine(dsn, future=True))

    # -----------------------------------------------------------------------
    # 등록 + 조회
    # -----------------------------------------------------------------------
    def register_resource(
        self,
        *,
        domain_code: str,
        resource_code: str,
        schema_name: str,
        table_name: str,
    ) -> ResourceRef:
        """yaml 의 (domain_code, resource_code) → 실제 (schema, table) 매핑 + reflect."""
        key = (domain_code, resource_code)
        ref = ResourceRef(
            domain_code=domain_code,
            resource_code=resource_code,
            schema_name=schema_name,
            table_name=table_name,
        )
        self._resources[key] = ref
        # reflect — fail fast: table 이 없으면 즉시 OperationalError.
        self._reflect(ref)
        return ref

    def get_table(self, *, domain_code: str, resource_code: str) -> Table:
        key = (domain_code, resource_code)
        if key not in self._resources:
            raise KeyError(f"unregistered resource: {domain_code}.{resource_code}")
        return self._reflect(self._resources[key])

    def _reflect(self, ref: ResourceRef) -> Table:
        if ref.fqn in self._tables:
            return self._tables[ref.fqn]
        tbl = Table(
            ref.table_name,
            self.metadata,
            schema=ref.schema_name,
            autoload_with=self.engine,
            extend_existing=True,
        )
        self._tables[ref.fqn] = tbl
        return tbl

    # -----------------------------------------------------------------------
    # CRUD — Core 기반 (ORM 클래스 없음)
    # -----------------------------------------------------------------------
    def insert(
        self,
        domain_code: str,
        resource_code: str,
        values: Mapping[str, Any],
    ) -> int:
        """1행 INSERT. RETURNING 의 첫 PK 반환."""
        tbl = self.get_table(domain_code=domain_code, resource_code=resource_code)
        pk_col = next(iter(tbl.primary_key.columns))
        stmt = insert(tbl).values(**values).returning(pk_col)
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
            new_id = result.scalar_one()
        return int(new_id)

    def select(
        self,
        domain_code: str,
        resource_code: str,
        *,
        where: Mapping[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        tbl = self.get_table(domain_code=domain_code, resource_code=resource_code)
        stmt = select(tbl).limit(limit)
        if where:
            for k, v in where.items():
                stmt = stmt.where(tbl.c[k] == v)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_row_to_dict(r) for r in rows]

    def update(
        self,
        domain_code: str,
        resource_code: str,
        *,
        where: Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> int:
        tbl = self.get_table(domain_code=domain_code, resource_code=resource_code)
        stmt = update(tbl)
        for k, v in where.items():
            stmt = stmt.where(tbl.c[k] == v)
        stmt = stmt.values(**values)
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
        return int(result.rowcount or 0)

    def delete_(
        self,
        domain_code: str,
        resource_code: str,
        *,
        where: Mapping[str, Any],
    ) -> int:
        tbl = self.get_table(domain_code=domain_code, resource_code=resource_code)
        stmt = delete(tbl)
        for k, v in where.items():
            stmt = stmt.where(tbl.c[k] == v)
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
        return int(result.rowcount or 0)

    # -----------------------------------------------------------------------
    # JOIN — sensor + reading
    # -----------------------------------------------------------------------
    def join_select(
        self,
        *,
        left: tuple[str, str],
        right: tuple[str, str],
        on: tuple[str, str],
        where: Mapping[str, Any] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """generic JOIN — left.on[0] = right.on[1].

        left/right 는 (domain_code, resource_code) 튜플.
        """
        l_tbl = self.get_table(domain_code=left[0], resource_code=left[1])
        r_tbl = self.get_table(domain_code=right[0], resource_code=right[1])
        join_clause = l_tbl.c[on[0]] == r_tbl.c[on[1]]
        stmt = select(l_tbl, r_tbl).select_from(l_tbl.join(r_tbl, join_clause))
        if where:
            for k, v in where.items():
                # left 우선 컬럼 매칭.
                col = l_tbl.c.get(k) if k in l_tbl.c else r_tbl.c.get(k)
                if col is None:
                    raise KeyError(f"column {k} not found in either table")
                stmt = stmt.where(col == v)
        stmt = stmt.limit(limit)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).fetchall()
        return [_row_to_dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Vector — 도메인별 차원 동적 처리
    # -----------------------------------------------------------------------
    def vector_insert(
        self,
        domain_code: str,
        resource_code: str,
        *,
        pk_column: str,
        pk_value: int,
        embedding: list[float],
        model_name: str | None = None,
    ) -> None:
        """차원에 무관한 vector INSERT.

        pgvector 의 vector 타입은 SQLAlchemy reflection 으로 감지 안 될 수 있어
        text() 로 명시 캐스팅. 차원은 caller 가 검증 (registry 가 yaml 의 dim 보고
        검증).
        """
        tbl = self.get_table(domain_code=domain_code, resource_code=resource_code)
        # vector 컬럼은 pgvector 확장 타입. SQLAlchemy 는 NullType 으로 인식 — 명시 캐스팅.
        embedding_str = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
        cols: list[str] = [pk_column, "embedding"]
        params: dict[str, Any] = {"pk": pk_value, "emb": embedding_str}
        if "model_name" in tbl.c and model_name is not None:
            cols.append("model_name")
            params["model"] = model_name
        col_list = ", ".join(cols)
        placeholders = ", ".join(
            ":pk" if c == pk_column else (":model" if c == "model_name" else "CAST(:emb AS vector)")
            for c in cols
        )
        sql = (
            f'INSERT INTO "{tbl.schema}"."{tbl.name}" ({col_list}) '
            f"VALUES ({placeholders})"
        )
        with self.engine.begin() as conn:
            conn.execute(text(sql), params)

    def vector_dimension_of(self, model_name: str) -> int:
        """모델명 → 차원. 미등록 모델은 KeyError."""
        return self.EMBEDDING_DIMENSIONS[model_name]

    # -----------------------------------------------------------------------
    # 진단
    # -----------------------------------------------------------------------
    def list_columns(
        self, *, domain_code: str, resource_code: str
    ) -> list[tuple[str, str]]:
        """(컬럼명, 타입) 리스트 — Designer UI / Mart Designer 의 입력 검증용."""
        tbl = self.get_table(domain_code=domain_code, resource_code=resource_code)
        return [(c.name, str(c.type)) for c in tbl.columns]


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------
def _row_to_dict(row: Row[Any]) -> dict[str, Any]:
    return dict(row._mapping)


def sync_dsn_from_settings() -> str:
    """app.config 의 database_url 을 sync DSN 으로 변환."""
    from app.config import get_settings

    url = get_settings().database_url
    if url.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + url[len("postgresql+asyncpg://") :]
    return url


__all__ = [
    "CoreOnlyRegistry",
    "HybridResourceRegistry",
    "ResourceRef",
    "option_a_dynamic_orm_class",
    "sync_dsn_from_settings",
]
