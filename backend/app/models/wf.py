"""wf schema ORM — Visual ETL Designer 의 워크플로 정의 (Phase 3.2.1).

실행 이력은 `run.pipeline_run` / `run.node_run` (`app/models/run.py`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


__all__ = ["EdgeDefinition", "NodeDefinition", "WorkflowDefinition"]
