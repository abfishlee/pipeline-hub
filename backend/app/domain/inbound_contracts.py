"""Inbound channel payload contracts.

The contract table is intentionally small: it lets operators define the JSON
shape a push sender must follow before data is accepted into audit.inbound_event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(slots=True)
class ContractValidationResult:
    ok: bool
    errors: list[str]


def ensure_contract_table(session: Session) -> None:
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS domain.inbound_channel_contract (
                channel_code TEXT PRIMARY KEY
                    REFERENCES domain.inbound_channel(channel_code) ON DELETE CASCADE,
                payload_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
                sample_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                item_path TEXT,
                reject_on_schema_mismatch BOOLEAN NOT NULL DEFAULT true,
                notes TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )


def get_contract(session: Session, channel_code: str) -> dict[str, Any] | None:
    ensure_contract_table(session)
    row = session.execute(
        text(
            """
            SELECT channel_code, payload_schema, sample_payload, item_path,
                   reject_on_schema_mismatch, notes, updated_at
              FROM domain.inbound_channel_contract
             WHERE channel_code = :channel_code
            """
        ),
        {"channel_code": channel_code},
    ).first()
    if row is None:
        return None
    return {
        "channel_code": str(row.channel_code),
        "payload_schema": row.payload_schema or {},
        "sample_payload": row.sample_payload or {},
        "item_path": str(row.item_path) if row.item_path else None,
        "reject_on_schema_mismatch": bool(row.reject_on_schema_mismatch),
        "notes": str(row.notes) if row.notes else None,
        "updated_at": row.updated_at,
    }


def upsert_contract(
    session: Session,
    *,
    channel_code: str,
    payload_schema: dict[str, Any],
    sample_payload: dict[str, Any],
    item_path: str | None,
    reject_on_schema_mismatch: bool = True,
    notes: str | None = None,
) -> dict[str, Any]:
    ensure_contract_table(session)
    session.execute(
        text(
            """
            INSERT INTO domain.inbound_channel_contract
                (channel_code, payload_schema, sample_payload, item_path,
                 reject_on_schema_mismatch, notes, updated_at)
            VALUES
                (:channel_code, CAST(:payload_schema AS JSONB),
                 CAST(:sample_payload AS JSONB), :item_path,
                 :reject_on_schema_mismatch, :notes, now())
            ON CONFLICT (channel_code) DO UPDATE SET
                payload_schema = EXCLUDED.payload_schema,
                sample_payload = EXCLUDED.sample_payload,
                item_path = EXCLUDED.item_path,
                reject_on_schema_mismatch = EXCLUDED.reject_on_schema_mismatch,
                notes = EXCLUDED.notes,
                updated_at = now()
            """
        ),
        {
            "channel_code": channel_code,
            "payload_schema": _json(payload_schema),
            "sample_payload": _json(sample_payload),
            "item_path": item_path,
            "reject_on_schema_mismatch": reject_on_schema_mismatch,
            "notes": notes,
        },
    )
    loaded = get_contract(session, channel_code)
    assert loaded is not None
    return loaded


def validate_payload_against_contract(
    payload: Any, contract: dict[str, Any] | None
) -> ContractValidationResult:
    if contract is None:
        return ContractValidationResult(ok=True, errors=[])
    schema = contract.get("payload_schema") or {}
    errors: list[str] = []
    _validate_object(payload, schema, "$", errors)
    return ContractValidationResult(ok=not errors, errors=errors)


def _validate_object(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object")
            return
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required")
        props = schema.get("properties") or {}
        for key, sub_schema in props.items():
            if key in value and isinstance(sub_schema, dict):
                _validate_object(value[key], sub_schema, f"{path}.{key}", errors)
        return
    if expected_type == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected array")
            return
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate_object(item, item_schema, f"{path}[{idx}]", errors)
        return
    if expected_type == "string" and not isinstance(value, str):
        errors.append(f"{path}: expected string")
    elif expected_type in {"number", "integer"} and not isinstance(value, int | float):
        errors.append(f"{path}: expected number")
    elif expected_type == "boolean" and not isinstance(value, bool):
        errors.append(f"{path}: expected boolean")


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


__all__ = [
    "ContractValidationResult",
    "ensure_contract_table",
    "get_contract",
    "upsert_contract",
    "validate_payload_against_contract",
]
