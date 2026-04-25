"""wf schema ORM — Visual ETL Designer 의 워크플로 정의 (Phase 3.2.1+).

실행 이력은 `run.pipeline_run` / `run.node_run` (`app/models/run.py`).

Phase 3.2.5 추가:
  - SqlQuery / SqlQueryVersion — SQL Studio 의 자산 + 라이프사이클 (DRAFT → PENDING →
    APPROVED/REJECTED/SUPERSEDED). 승인된 SQL 만 `SQL_TRANSFORM` 노드 config 로 재사용.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class WorkflowDefinition(Base):
    """사용자가 그린 DAG 메타. status DRAFT → PUBLISHED → ARCHIVED."""

    __tablename__ = "workflow_definition"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_workflow_name_version"),
        CheckConstraint(
            "status IN ('DRAFT','PUBLISHED','ARCHIVED')",
            name="ck_workflow_status",
        ),
        {"schema": "wf"},
    )

    workflow_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 3.2.7 — 배치 스케줄 메타. cron 표현식은 5-field UTC 기준.
    schedule_cron: Mapped[str | None] = mapped_column(Text)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    nodes: Mapped[list[NodeDefinition]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    edges: Mapped[list[EdgeDefinition]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )


class NodeDefinition(Base):
    __tablename__ = "node_definition"
    __table_args__ = (
        UniqueConstraint("workflow_id", "node_key", name="uq_node_workflow_key"),
        CheckConstraint(
            "node_type IN ('NOOP','SOURCE_API','SQL_TRANSFORM','DEDUP','DQ_CHECK','LOAD_MASTER','NOTIFY')",
            name="ck_node_type",
        ),
        {"schema": "wf"},
    )

    node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("wf.workflow_definition.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    node_key: Mapped[str] = mapped_column(Text, nullable=False)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    position_x: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    position_y: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    workflow: Mapped[WorkflowDefinition] = relationship(back_populates="nodes")


class EdgeDefinition(Base):
    __tablename__ = "edge_definition"
    __table_args__ = (
        UniqueConstraint("workflow_id", "from_node_id", "to_node_id", name="uq_edge_workflow_pair"),
        CheckConstraint("from_node_id <> to_node_id", name="ck_edge_no_self_loop"),
        {"schema": "wf"},
    )

    edge_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("wf.workflow_definition.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    from_node_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("wf.node_definition.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    to_node_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("wf.node_definition.node_id", ondelete="CASCADE"),
        nullable=False,
    )
    condition_expr: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    workflow: Mapped[WorkflowDefinition] = relationship(back_populates="edges")


class SqlQuery(Base):
    """SQL Studio 자산 — 사용자가 이름 붙인 SQL 자원의 메타.

    실제 SQL 본문은 `SqlQueryVersion` 에. `current_version_id` 는 가장 최근 APPROVED
    버전을 가리키는 캐시 (SUPERSEDED 정책상 항상 최신만 유효).
    """

    __tablename__ = "sql_query"
    __table_args__ = (
        UniqueConstraint("name", name="uq_sql_query_name"),
        {"schema": "wf"},
    )

    sql_query_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ctl.app_user.user_id"), nullable=False
    )
    # 후행 FK — sql_query_version 이 먼저 생성된 뒤 alter 로 거는 형태.
    # SQLAlchemy 의 metadata create_all 에서 양쪽 자기참조 사이클을 풀기 위해
    # use_alter + name 을 ForeignKey 인자로 직접 부여 (mapped_column 에는 없음).
    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "wf.sql_query_version.sql_query_version_id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_sql_query_current_version",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list[SqlQueryVersion]] = relationship(
        back_populates="query",
        cascade="all, delete-orphan",
        foreign_keys="SqlQueryVersion.sql_query_id",
    )


class SqlQueryVersion(Base):
    """SQL 본문의 한 버전.

    상태머신:
      DRAFT       — 작성자가 자유롭게 수정 가능 (저장 시 새 row 가 아니라 기존 row update).
      PENDING     — submit 후 검토 대기. APPROVER 의 결재 대상.
      APPROVED    — 승인됨. SQL_TRANSFORM 노드에 연결 가능. 동일 query 의 이전 APPROVED
                    버전은 자동 SUPERSEDED 로 marking.
      REJECTED    — 반려됨. 새 DRAFT 버전을 만들어 재제출해야 함.
      SUPERSEDED  — 더 새로운 APPROVED 버전이 등장하여 비활성.
    """

    __tablename__ = "sql_query_version"
    __table_args__ = (
        UniqueConstraint("sql_query_id", "version_no", name="uq_sql_query_version_no"),
        CheckConstraint(
            "status IN ('DRAFT','PENDING','APPROVED','REJECTED','SUPERSEDED')",
            name="ck_sql_query_version_status",
        ),
        {"schema": "wf"},
    )

    sql_query_version_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    sql_query_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("wf.sql_query.sql_query_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)
    referenced_tables: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    parent_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("wf.sql_query_version.sql_query_version_id")
    )
    submitted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    query: Mapped[SqlQuery] = relationship(back_populates="versions", foreign_keys=[sql_query_id])


class PipelineRelease(Base):
    """DRAFT → PUBLISHED 전환 이력 (Phase 3.2.6).

    PUBLISHED 전환 시 1행 INSERT — 해당 시점의 그래프 스냅샷 + 이전 PUBLISHED 와의 diff
    요약을 보존. 원본 DRAFT 가 이후 수정되거나 삭제돼도 release 이력은 불변.
    """

    __tablename__ = "pipeline_release"
    __table_args__ = (
        UniqueConstraint("workflow_name", "version_no", name="uq_pipeline_release_name_version"),
        {"schema": "wf"},
    )

    release_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_name: Mapped[str] = mapped_column(Text, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_workflow_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("wf.workflow_definition.workflow_id", ondelete="SET NULL"),
    )
    released_workflow_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("wf.workflow_definition.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    released_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ctl.app_user.user_id"))
    released_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    change_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    nodes_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    edges_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )


__all__ = [
    "EdgeDefinition",
    "NodeDefinition",
    "PipelineRelease",
    "SqlQuery",
    "SqlQueryVersion",
    "WorkflowDefinition",
]
