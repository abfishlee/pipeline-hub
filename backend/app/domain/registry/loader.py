"""yaml/dict → domain.* 테이블 적재 (Phase 5.2.1).

yaml 형식 (예 — domains/agri.yaml):

    domain_code: agri
    name: 농축산물 가격
    description: v1 농축산물 가격 도메인 (legacy 보존)
    resources:
      - resource_code: PRICE_FACT
        canonical_table: mart.product_master   # v1 테이블 그대로 가리킴 (Q3 답변)
        fact_table: mart.price_fact
        standard_code_namespace: AGRI_FOOD
        embedding_model: hyperclova
        embedding_dim: 1536
      - resource_code: DAILY_AGG
        fact_table: mart.price_daily_agg
    standard_code_namespaces:
      - name: AGRI_FOOD
        std_code_table: mart.standard_code
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.domain import (
    DomainDefinition,
    ResourceDefinition,
    StandardCodeNamespace,
)


@dataclass(slots=True)
class LoadedDomain:
    domain_code: str
    resource_ids: dict[str, int] = field(default_factory=dict)
    namespace_ids: dict[str, int] = field(default_factory=dict)


def load_domain_from_yaml_path(session: Session, *, path: str | Path) -> LoadedDomain:
    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    return load_domain_from_dict(session, data=data)


def load_domain_from_dict(session: Session, *, data: Mapping[str, Any]) -> LoadedDomain:
    """yaml dict 를 domain.* 에 *upsert* (idempotent).

    재실행 시 같은 domain_code 의 row 가 있으면 schema_yaml 만 갱신 + resources 는
    UNIQUE(domain_code, resource_code, version) 에 의해 새 version 으로 처리.
    """
    domain_code = str(data["domain_code"])
    name = str(data.get("name") or domain_code)
    description = data.get("description")
    schema_yaml = dict(data)

    # 1) domain_definition upsert.
    insert_stmt = pg_insert(DomainDefinition).values(
        domain_code=domain_code,
        name=name,
        description=description,
        schema_yaml=schema_yaml,
        status="DRAFT",
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[DomainDefinition.domain_code],
        set_={
            "name": name,
            "description": description,
            "schema_yaml": schema_yaml,
            "updated_at": insert_stmt.excluded.updated_at,
        },
    )
    session.execute(upsert_stmt)

    out = LoadedDomain(domain_code=domain_code)

    # 2) standard_code_namespaces.
    for ns in data.get("standard_code_namespaces", []) or []:
        ns_name = str(ns.get("name") or "")
        if not ns_name:
            continue
        # 기존 매핑이 있으면 그대로 두고 namespace_id 만 가져옴.
        existing_ns = session.execute(
            select(StandardCodeNamespace).where(
                StandardCodeNamespace.domain_code == domain_code,
                StandardCodeNamespace.name == ns_name,
            )
        ).scalar_one_or_none()
        if existing_ns is None:
            new_ns = StandardCodeNamespace(
                domain_code=domain_code,
                name=ns_name,
                description=ns.get("description"),
                std_code_table=ns.get("std_code_table"),
            )
            session.add(new_ns)
            session.flush()
            out.namespace_ids[ns_name] = new_ns.namespace_id
        else:
            out.namespace_ids[ns_name] = existing_ns.namespace_id

    # 3) resource_definition.
    for res in data.get("resources", []) or []:
        rc = str(res.get("resource_code") or "")
        if not rc:
            continue
        existing_res = session.execute(
            select(ResourceDefinition).where(
                ResourceDefinition.domain_code == domain_code,
                ResourceDefinition.resource_code == rc,
                ResourceDefinition.version == int(res.get("version", 1)),
            )
        ).scalar_one_or_none()
        if existing_res is None:
            new_res = ResourceDefinition(
                domain_code=domain_code,
                resource_code=rc,
                canonical_table=res.get("canonical_table"),
                fact_table=res.get("fact_table"),
                standard_code_namespace=res.get("standard_code_namespace"),
                embedding_model=res.get("embedding_model"),
                embedding_table=res.get("embedding_table"),
                embedding_dim=res.get("embedding_dim"),
                version=int(res.get("version", 1)),
                status="DRAFT",
            )
            session.add(new_res)
            session.flush()
            out.resource_ids[rc] = new_res.resource_id
        else:
            existing_res.canonical_table = res.get("canonical_table") or existing_res.canonical_table
            existing_res.fact_table = res.get("fact_table") or existing_res.fact_table
            existing_res.standard_code_namespace = (
                res.get("standard_code_namespace") or existing_res.standard_code_namespace
            )
            existing_res.embedding_model = (
                res.get("embedding_model") or existing_res.embedding_model
            )
            existing_res.embedding_table = (
                res.get("embedding_table") or existing_res.embedding_table
            )
            existing_res.embedding_dim = res.get("embedding_dim") or existing_res.embedding_dim
            out.resource_ids[rc] = existing_res.resource_id

    session.flush()
    return out


__all__ = ["LoadedDomain", "load_domain_from_dict", "load_domain_from_yaml_path"]
