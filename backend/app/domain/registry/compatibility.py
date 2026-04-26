"""schema 호환성 판정 — backward / forward / full / none.

source_contract.schema_json 의 *새 버전* 이 *기존 버전* 과 호환되는지 검증.
Avro/Confluent 스키마 호환성 표준 따름:

  - backward  : 새 schema 로 *기존 데이터* 를 읽을 수 있어야 함
                (= 새 schema 가 기존 필드를 모두 알아봐야 함)
  - forward   : 기존 schema consumer 가 *새 데이터* 를 읽을 수 있어야 함
                (= 새 schema 가 기존 필드를 *제거 안 함*, 추가 필드는 nullable)
  - full      : backward + forward 모두 만족
  - none      : 검사 안 함

본 모듈은 *JSON Schema 스타일 dict* 를 기준으로 단순화한 호환성 검사. 본격적인
JSON Schema validator 는 후속 PoC 에서 jsonschema lib 도입 검토.

schema_json 형식 (예):
  {
    "fields": [
      {"name": "sku", "type": "string", "required": true},
      {"name": "price", "type": "number", "required": true},
      {"name": "discount", "type": "number", "required": false}
    ]
  }
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class FieldDef:
    name: str
    data_type: str
    required: bool

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> FieldDef:
        return cls(
            name=str(d.get("name") or ""),
            data_type=str(d.get("type") or "any"),
            required=bool(d.get("required", False)),
        )


@dataclass(slots=True, frozen=True)
class CompatibilityResult:
    """비교 결과."""

    mode: str
    is_compatible: bool
    breaking_changes: list[str] = field(default_factory=list)
    additive_changes: list[str] = field(default_factory=list)


def _fields_of(schema: Mapping[str, Any]) -> dict[str, FieldDef]:
    out: dict[str, FieldDef] = {}
    for f in schema.get("fields", []):
        if not isinstance(f, Mapping):
            continue
        fd = FieldDef.from_dict(f)
        if fd.name:
            out[fd.name] = fd
    return out


def _check_backward(old: dict[str, FieldDef], new: dict[str, FieldDef]) -> tuple[list[str], list[str]]:
    """새 schema 로 기존 데이터를 읽을 수 있어야 — 새 schema 가 기존 필드를 *알아봐야*.

    breaking:
      - 기존 required 필드가 새 schema 에서 *사라짐* (consumer 가 모름)
      - 기존 필드 type 이 *호환 불가능하게* 변경
      - 새 schema 가 *추가 required 필드* 도입 (구 데이터엔 그 필드 없음 — 못 읽음)
    additive: 새 schema 의 추가 *optional* 필드.
    """
    breaking: list[str] = []
    additive: list[str] = []
    for name, old_f in old.items():
        new_f = new.get(name)
        if new_f is None:
            if old_f.required:
                breaking.append(f"required field '{name}' removed in new schema")
            else:
                additive.append(f"optional field '{name}' removed (compatible)")
            continue
        if old_f.data_type != new_f.data_type and new_f.data_type != "any":
            breaking.append(
                f"field '{name}' type changed: {old_f.data_type} → {new_f.data_type}"
            )
    for name, new_f in new.items():
        if name in old:
            continue
        if new_f.required:
            breaking.append(f"new required field '{name}' added (old data lacks it)")
        else:
            additive.append(f"new optional field '{name}' added (compatible)")
    return breaking, additive


def _check_forward(old: dict[str, FieldDef], new: dict[str, FieldDef]) -> tuple[list[str], list[str]]:
    """기존 consumer 가 새 데이터 읽을 수 있어야 — 새 schema 가 기존 required 를 제거 X.

    breaking:
      - 기존 required 필드가 새 schema 에서 *제거* (구 consumer 가 그 필드 기대)
      - type 호환 불가 변경
      - 새 schema 의 *추가 required* (구 consumer 무시 — 사실 forward 에선 OK)
    """
    breaking: list[str] = []
    additive: list[str] = []
    for name, old_f in old.items():
        new_f = new.get(name)
        if new_f is None:
            if old_f.required:
                breaking.append(f"old required field '{name}' missing in new schema")
            else:
                additive.append(f"optional field '{name}' removed (forward-compatible)")
            continue
        if old_f.data_type != new_f.data_type and new_f.data_type != "any":
            breaking.append(
                f"field '{name}' type changed: {old_f.data_type} → {new_f.data_type}"
            )
    for name in new:
        if name not in old:
            additive.append(f"new field '{name}' (forward-compatible)")
    return breaking, additive


def check_schema_compatibility(
    *,
    old_schema: Mapping[str, Any] | None,
    new_schema: Mapping[str, Any],
    mode: str = "backward",
) -> CompatibilityResult:
    """schema 변경의 호환성 판정.

    `old_schema` 가 None 이면 *최초 등록* — 항상 호환 가능 (mode 무관).
    `mode='none'` 이면 검사 skip — 항상 호환.
    """
    if mode == "none":
        return CompatibilityResult(mode=mode, is_compatible=True)
    if old_schema is None:
        return CompatibilityResult(mode=mode, is_compatible=True)

    old = _fields_of(old_schema)
    new = _fields_of(new_schema)

    if mode == "backward":
        breaking, additive = _check_backward(old, new)
        return CompatibilityResult(
            mode=mode,
            is_compatible=not breaking,
            breaking_changes=breaking,
            additive_changes=additive,
        )
    if mode == "forward":
        breaking, additive = _check_forward(old, new)
        return CompatibilityResult(
            mode=mode,
            is_compatible=not breaking,
            breaking_changes=breaking,
            additive_changes=additive,
        )
    if mode == "full":
        b1, a1 = _check_backward(old, new)
        b2, a2 = _check_forward(old, new)
        # 두 방향 다 호환되어야.
        all_breaking = list(set(b1 + b2))
        all_additive = list(set(a1 + a2))
        return CompatibilityResult(
            mode=mode,
            is_compatible=not all_breaking,
            breaking_changes=all_breaking,
            additive_changes=all_additive,
        )
    raise ValueError(f"unknown mode: {mode}")


__all__ = ["CompatibilityResult", "FieldDef", "check_schema_compatibility"]
