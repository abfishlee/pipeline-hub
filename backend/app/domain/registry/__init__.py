"""v2 generic registry (Phase 5.2.1).

ADR-0017 Hybrid 채택 — v1 의 정적 ORM 은 그대로 두고, v2 generic resource 의 *데이터*
는 SQLAlchemy Core + reflection. 본 패키지는 *registry 메타* (정적 ORM) 위에서 동작
하는 helper:

  - loader: yaml 또는 dict → DB row 적재 (`domain.*` 테이블)
  - selector: source_contract.resource_selector_json 으로 raw payload 분기
  - compatibility: schema_version 변경의 backward / forward / breaking 판정
"""

from __future__ import annotations

from app.domain.registry.compatibility import (
    CompatibilityResult,
    check_schema_compatibility,
)
from app.domain.registry.loader import (
    LoadedDomain,
    load_domain_from_dict,
    load_domain_from_yaml_path,
)
from app.domain.registry.selector import (
    SelectorMatch,
    match_resource_selector,
)

__all__ = [
    "CompatibilityResult",
    "LoadedDomain",
    "SelectorMatch",
    "check_schema_compatibility",
    "load_domain_from_dict",
    "load_domain_from_yaml_path",
    "match_resource_selector",
]
