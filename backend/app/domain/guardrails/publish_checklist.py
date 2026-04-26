"""Composable publish checklist.

엔티티 (source_contract / field_mapping / dq_rule / mart_load_policy / sql_asset)
가 PUBLISHED 상태로 가기 전에 *통과해야 하는 체크 목록* 을 composable 하게 정의.

Phase 5 MVP 는 *runner 인프라* 만 제공. 실제 체크 항목은 5.2.1 의 entity 도착 시
plug-in. 본 모듈은:
  - `CheckSpec` 인터페이스
  - `PublishChecklist` runner
  - 기본 체크 2종 (`HasStatusApproved`, `RequiredFieldsPresent`)

사용 예:

    >>> spec = PublishChecklist(checks=[
    ...     HasStatusApproved(entity_status="APPROVED"),
    ...     RequiredFieldsPresent(fields={"target_table", "load_policy"}, payload=..)
    ... ])
    >>> result = spec.run()
    >>> assert result.is_pass
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True, frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(slots=True, frozen=True)
class ChecklistResult:
    results: list[CheckResult]

    @property
    def is_pass(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failed(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]


class CheckSpec(Protocol):
    """1개 체크 항목."""

    name: str

    def run(self) -> CheckResult: ...


# ---------------------------------------------------------------------------
# 기본 체크 2종 — 5.2.1 에서 entity 별로 추가
# ---------------------------------------------------------------------------
@dataclass(slots=True, frozen=True)
class HasStatusApproved:
    """엔티티 status 가 APPROVED 인지 (PUBLISHED 진입의 1차 조건)."""

    entity_status: str
    name: str = "has_status_approved"

    def run(self) -> CheckResult:
        ok = self.entity_status == "APPROVED"
        return CheckResult(
            name=self.name,
            passed=ok,
            detail=("status=APPROVED" if ok else f"status={self.entity_status} (expected APPROVED)"),
        )


@dataclass(slots=True, frozen=True)
class RequiredFieldsPresent:
    """엔티티 payload 의 필수 필드 검증."""

    fields: frozenset[str]
    payload: Mapping[str, Any]
    name: str = "required_fields_present"

    def run(self) -> CheckResult:
        missing = sorted(f for f in self.fields if f not in self.payload or self.payload[f] in (None, "", []))
        if missing:
            return CheckResult(
                name=self.name,
                passed=False,
                detail=f"missing: {missing}",
            )
        return CheckResult(name=self.name, passed=True, detail="all present")


@dataclass(slots=True, frozen=True)
class CustomCheck:
    """ad-hoc 체크 — caller 가 callable + name 만 주입.

    callable 은 () → bool 또는 () → tuple[bool, str].
    """

    name: str
    fn: Any  # Callable[[], bool] | Callable[[], tuple[bool, str]]

    def run(self) -> CheckResult:
        out = self.fn()
        if isinstance(out, tuple):
            ok, detail = out
            return CheckResult(name=self.name, passed=bool(ok), detail=str(detail))
        return CheckResult(name=self.name, passed=bool(out), detail="")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class PublishChecklist:
    checks: list[CheckSpec] = field(default_factory=list)

    def add(self, check: CheckSpec) -> PublishChecklist:
        self.checks.append(check)
        return self

    def run(self) -> ChecklistResult:
        return ChecklistResult(results=[c.run() for c in self.checks])


__all__ = [
    "CheckResult",
    "CheckSpec",
    "ChecklistResult",
    "CustomCheck",
    "HasStatusApproved",
    "PublishChecklist",
    "RequiredFieldsPresent",
]
