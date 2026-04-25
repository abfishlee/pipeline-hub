"""SQL Studio domain — sandbox preview / EXPLAIN / 승인 플로우 (Phase 3.2.5).

Phase 3.2.4 (`/v1/sql-studio/validate`) 가 sqlglot 정적 분석만 했다면, 본 모듈은
**실제 PostgreSQL 에 SQL 을 띄워보는** 부분을 담당한다.

설계 핵심
---------
1. **sandbox 격리** — 사용자 SQL 은 매 호출 새 트랜잭션에서 실행되며 항상 ROLLBACK 으로
   끝난다. `BEGIN; SET LOCAL transaction_read_only = ON;` 으로 read-only 강제 → 어떤
   변형 SQL 이 들어와도 실제 데이터 쓰기는 불가능. (sqlglot 화이트리스트가 1차 방어,
   read_only 가 2차 방어, ROLLBACK 이 3차 방어.)
2. **타임아웃** — `SET LOCAL statement_timeout = N` 으로 PG 측 강제 종료. 기본 30s.
3. **결과 limit** — preview 는 `LIMIT 1000` 을 sqlglot AST 에 자동 부착. 사용자가 이미
   더 작은 LIMIT 을 걸어두면 그대로 둠.
4. **EXPLAIN** — `EXPLAIN (FORMAT JSON, COSTS OFF) <user sql>` 로 감싸 실행. 실제 데이터를
   읽지 않으므로 read-only + ROLLBACK 만 적용 (LIMIT 는 미적용).
5. **승인 상태머신** — `SqlQueryVersion.status`:
       DRAFT      → submit       → PENDING
       PENDING    → approve      → APPROVED  (이전 APPROVED 는 SUPERSEDED 로 강등)
       PENDING    → reject       → REJECTED
       APPROVED   → (새 버전 APPROVED)       → SUPERSEDED
   APPROVED 만 SQL_TRANSFORM 노드 config 로 재사용 가능.
6. **audit 기록** — VALIDATE/PREVIEW/EXPLAIN 모두 `audit.sql_execution_log` 에 1행씩
   남긴다 (SUCCESS / BLOCKED / FAILED + 실행 시간 + row_count + sql_query_version_id 옵션).

본 도메인은 sync session 기반 — psycopg3 의 `SET LOCAL` / `statement_timeout` 등
PG 트랜잭션 컨텍스트를 다루기 쉽고, async 변환 시 발생하는 connection-leak 위험을 피한다.
호출자(API 레이어) 가 thread offload 를 책임진다.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlglot
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.integrations.sqlglot_validator import SqlValidationError, validate
from app.models.audit import SqlExecutionLog
from app.models.wf import SqlQuery, SqlQueryVersion

# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------


@dataclass
class PreviewResult:
    """`preview()` / `explain()` 반환. JSON-serializable."""

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: int = 0


@dataclass
class ExplainResult:
    plan_json: list[dict[str, Any]]
    elapsed_ms: int


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
DEFAULT_PREVIEW_LIMIT = 1000
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _hash_sql(sql: str) -> str:
    return hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()


def _attach_limit(sql: str, limit: int) -> str:
    """sqlglot AST 로 LIMIT 자동 부착. 사용자가 더 작은 LIMIT 을 이미 걸었으면 보존."""
    try:
        ast = sqlglot.parse_one(sql, read="postgres")
    except Exception:
        # validate() 가 이미 통과한 SQL 이라 여기 도달하면 안 됨. 안전하게 래핑.
        return f"SELECT * FROM ({sql}) AS _sandbox LIMIT {limit}"
    existing = ast.args.get("limit")
    if existing is not None:
        try:
            user_limit = int(existing.expression.this)
        except (AttributeError, ValueError, TypeError):
            user_limit = None
        if user_limit is not None and user_limit <= limit:
            return ast.sql(dialect="postgres")
    ast.set("limit", sqlglot.exp.Limit(expression=sqlglot.exp.Literal.number(limit)))
    return ast.sql(dialect="postgres")


def _audit_row(
    user_id: int,
    sql_text: str,
    *,
    execution_kind: str,
    status: str,
    row_count: int | None = None,
    error_message: str | None = None,
    sql_query_version_id: int | None = None,
    target_schema: str | None = None,
    started_at: datetime | None = None,
) -> SqlExecutionLog:
    return SqlExecutionLog(
        user_id=user_id,
        sql_text=sql_text,
        sql_hash=_hash_sql(sql_text),
        execution_kind=execution_kind,
        target_schema=target_schema,
        status=status,
        row_count=row_count,
        error_message=error_message,
        sql_query_version_id=sql_query_version_id,
        started_at=started_at or datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# VALIDATE — sqlglot 정적 + audit 기록
# ---------------------------------------------------------------------------
@dataclass
class ValidateOutcome:
    valid: bool
    error: str | None
    referenced_tables: list[str]


def validate_with_audit(session: Session, *, user_id: int, sql: str) -> ValidateOutcome:
    """3.2.4 의 validate 와 동등하지만 audit row 를 남기고 referenced_tables 도 정렬해 반환."""
    try:
        _ast, refs = validate(sql)
    except SqlValidationError as exc:
        session.add(
            _audit_row(
                user_id,
                sql,
                execution_kind="VALIDATE",
                status="BLOCKED",
                error_message=str(exc),
            )
        )
        return ValidateOutcome(valid=False, error=str(exc), referenced_tables=[])
    session.add(
        _audit_row(
            user_id,
            sql,
            execution_kind="VALIDATE",
            status="SUCCESS",
        )
    )
    return ValidateOutcome(valid=True, error=None, referenced_tables=sorted(refs))


# ---------------------------------------------------------------------------
# PREVIEW — read-only sandbox 실행 + LIMIT 강제
# ---------------------------------------------------------------------------
def preview(
    session: Session,
    *,
    user_id: int,
    sql: str,
    limit: int = DEFAULT_PREVIEW_LIMIT,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    sql_query_version_id: int | None = None,
) -> PreviewResult:
    """sqlglot 통과 → read-only 트랜잭션에서 LIMIT 부착해 실행 → ROLLBACK.

    호출 후 session 은 ROLLBACK 된 상태이므로 호출자가 audit row commit 을 직접 책임진다
    (함수 내부에서 audit row 를 add 했지만 ROLLBACK 으로 사라지는 문제를 피하기 위해
    audit 는 `session.commit()` 후 별도 sub-transaction 으로 처리).
    """
    started = datetime.now(UTC)
    t0 = time.monotonic()
    try:
        _ast, _refs = validate(sql)
    except SqlValidationError as exc:
        _commit_audit(
            session,
            _audit_row(
                user_id,
                sql,
                execution_kind="PREVIEW",
                status="BLOCKED",
                error_message=str(exc),
                sql_query_version_id=sql_query_version_id,
                started_at=started,
            ),
        )
        raise ValidationError(str(exc)) from exc

    # LIMIT 강제 + read-only sandbox.
    bounded_sql = _attach_limit(sql, limit)
    columns: list[str] = []
    rows: list[list[Any]] = []
    error: str | None = None
    try:
        with session.begin_nested():  # SAVEPOINT — 명시적 ROLLBACK 으로 안전성 강화.
            session.execute(text(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}"))
            session.execute(text("SET LOCAL transaction_read_only = ON"))
            result = session.execute(text(bounded_sql))
            columns = list(result.keys())
            fetched = result.fetchmany(limit)
            rows = [list(r) for r in fetched]
            # 의도적 ROLLBACK — read-only 라 사실상 변화 없음, 명시성 차원.
            raise _RollbackSentinel()
    except _RollbackSentinel:
        pass
    except Exception as exc:
        error = str(exc)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if error is not None:
        _commit_audit(
            session,
            _audit_row(
                user_id,
                sql,
                execution_kind="PREVIEW",
                status="FAILED",
                error_message=error,
                sql_query_version_id=sql_query_version_id,
                started_at=started,
            ),
        )
        raise ValidationError(f"sandbox preview failed: {error}")

    truncated = len(rows) >= limit
    _commit_audit(
        session,
        _audit_row(
            user_id,
            sql,
            execution_kind="PREVIEW",
            status="SUCCESS",
            row_count=len(rows),
            sql_query_version_id=sql_query_version_id,
            started_at=started,
        ),
    )
    return PreviewResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        elapsed_ms=elapsed_ms,
    )


class _RollbackSentinel(Exception):
    """`session.begin_nested()` 컨텍스트를 의도적으로 빠져나오기 위한 내부 신호."""


def _commit_audit(session: Session, log: SqlExecutionLog) -> None:
    """audit row 만 별도 트랜잭션으로 커밋 — preview/explain 의 ROLLBACK 영향 차단."""
    try:
        session.add(log)
        session.commit()
    except Exception:
        session.rollback()
        # audit 실패가 본 호출 결과를 깨뜨리진 않게. 다만 logging.
        # (loguru / structlog 사용 시 여기서 logger.warning)
        pass


# ---------------------------------------------------------------------------
# EXPLAIN
# ---------------------------------------------------------------------------
def explain(
    session: Session,
    *,
    user_id: int,
    sql: str,
    sql_query_version_id: int | None = None,
) -> ExplainResult:
    """`EXPLAIN (FORMAT JSON, COSTS OFF)` 결과 반환. sandbox 와 동일한 격리."""
    started = datetime.now(UTC)
    t0 = time.monotonic()
    try:
        validate(sql)
    except SqlValidationError as exc:
        _commit_audit(
            session,
            _audit_row(
                user_id,
                sql,
                execution_kind="EXPLAIN",
                status="BLOCKED",
                error_message=str(exc),
                sql_query_version_id=sql_query_version_id,
                started_at=started,
            ),
        )
        raise ValidationError(str(exc)) from exc

    plan_json: list[dict[str, Any]] = []
    error: str | None = None
    try:
        with session.begin_nested():
            session.execute(text("SET LOCAL transaction_read_only = ON"))
            result = session.execute(text(f"EXPLAIN (FORMAT JSON, COSTS OFF) {sql}"))
            row = result.first()
            if row is not None and row[0] is not None:
                # psycopg3 + JSON output: row[0] 은 list/dict.
                plan_json = list(row[0]) if isinstance(row[0], list) else [row[0]]
            raise _RollbackSentinel()
    except _RollbackSentinel:
        pass
    except Exception as exc:
        error = str(exc)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if error is not None:
        _commit_audit(
            session,
            _audit_row(
                user_id,
                sql,
                execution_kind="EXPLAIN",
                status="FAILED",
                error_message=error,
                sql_query_version_id=sql_query_version_id,
                started_at=started,
            ),
        )
        raise ValidationError(f"EXPLAIN failed: {error}")

    _commit_audit(
        session,
        _audit_row(
            user_id,
            sql,
            execution_kind="EXPLAIN",
            status="SUCCESS",
            sql_query_version_id=sql_query_version_id,
            started_at=started,
        ),
    )
    return ExplainResult(plan_json=plan_json, elapsed_ms=elapsed_ms)


# ---------------------------------------------------------------------------
# Query / Version CRUD + 승인 상태머신
# ---------------------------------------------------------------------------
def create_query(
    session: Session,
    *,
    name: str,
    description: str | None,
    sql_text: str,
    owner_user_id: int,
) -> SqlQueryVersion:
    """SqlQuery + 첫 DRAFT version 동시 생성."""
    name = name.strip()
    if not name:
        raise ValidationError("name 은 비어 있을 수 없습니다.")

    existing = session.execute(select(SqlQuery).where(SqlQuery.name == name)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"sql_query name '{name}' already exists")

    # validate 는 정적 통과 보장 — referenced_tables 까지 추출.
    try:
        _ast, refs = validate(sql_text)
        referenced = sorted(refs)
    except SqlValidationError as exc:
        raise ValidationError(str(exc)) from exc

    query = SqlQuery(
        name=name,
        description=description,
        owner_user_id=owner_user_id,
    )
    session.add(query)
    session.flush()

    version = SqlQueryVersion(
        sql_query_id=query.sql_query_id,
        version_no=1,
        sql_text=sql_text,
        referenced_tables=referenced,
        status="DRAFT",
    )
    session.add(version)
    session.flush()

    query.current_version_id = version.sql_query_version_id
    session.flush()
    return version


def add_version(
    session: Session,
    *,
    sql_query_id: int,
    sql_text: str,
    owner_user_id: int,
) -> SqlQueryVersion:
    """기존 query 에 새 DRAFT version 추가 (이전 버전이 APPROVED 든 REJECTED 든 무관)."""
    query = session.get(SqlQuery, sql_query_id)
    if query is None:
        raise NotFoundError(f"sql_query {sql_query_id} not found")
    if query.owner_user_id != owner_user_id:
        # 소유자만 새 DRAFT 추가. ADMIN 우회는 API 레이어에서 처리.
        raise ValidationError("only the owner can add a new draft version")

    try:
        _ast, refs = validate(sql_text)
        referenced = sorted(refs)
    except SqlValidationError as exc:
        raise ValidationError(str(exc)) from exc

    last_version_no = session.execute(
        select(SqlQueryVersion.version_no)
        .where(SqlQueryVersion.sql_query_id == sql_query_id)
        .order_by(SqlQueryVersion.version_no.desc())
        .limit(1)
    ).scalar_one()
    parent = session.execute(
        select(SqlQueryVersion)
        .where(SqlQueryVersion.sql_query_id == sql_query_id)
        .order_by(SqlQueryVersion.version_no.desc())
        .limit(1)
    ).scalar_one()
    new_version = SqlQueryVersion(
        sql_query_id=sql_query_id,
        version_no=last_version_no + 1,
        sql_text=sql_text,
        referenced_tables=referenced,
        status="DRAFT",
        parent_version_id=parent.sql_query_version_id,
    )
    session.add(new_version)
    session.flush()
    query.updated_at = datetime.now(UTC)
    return new_version


def submit_version(
    session: Session, *, sql_query_version_id: int, by_user_id: int
) -> SqlQueryVersion:
    """DRAFT → PENDING. 작성자 본인만."""
    version = _get_version_or_404(session, sql_query_version_id)
    if version.status != "DRAFT":
        raise ConflictError(f"version {sql_query_version_id} is {version.status}, not DRAFT")

    query = session.get(SqlQuery, version.sql_query_id)
    if query is not None and query.owner_user_id != by_user_id:
        raise ValidationError("only the owner can submit a version for approval")

    version.status = "PENDING"
    version.submitted_by = by_user_id
    version.submitted_at = datetime.now(UTC)
    session.flush()
    return version


def approve_version(
    session: Session,
    *,
    sql_query_version_id: int,
    reviewer_user_id: int,
    comment: str | None = None,
) -> SqlQueryVersion:
    """PENDING → APPROVED. 같은 query 의 이전 APPROVED 는 SUPERSEDED 로 강등.

    self-approval 차단 — submit 한 사람과 reviewer 가 같으면 거부.
    """
    version = _get_version_or_404(session, sql_query_version_id)
    if version.status != "PENDING":
        raise ConflictError(f"version {sql_query_version_id} is {version.status}, not PENDING")
    if version.submitted_by == reviewer_user_id:
        raise ValidationError("self-approval is not allowed")

    # 이전 APPROVED 모두 SUPERSEDED.
    prev_approved = session.execute(
        select(SqlQueryVersion).where(
            SqlQueryVersion.sql_query_id == version.sql_query_id,
            SqlQueryVersion.status == "APPROVED",
        )
    ).scalars()
    for prev in prev_approved:
        prev.status = "SUPERSEDED"

    version.status = "APPROVED"
    version.reviewed_by = reviewer_user_id
    version.reviewed_at = datetime.now(UTC)
    version.review_comment = comment

    query = session.get(SqlQuery, version.sql_query_id)
    if query is not None:
        query.current_version_id = version.sql_query_version_id
        query.updated_at = datetime.now(UTC)

    session.flush()
    return version


def reject_version(
    session: Session,
    *,
    sql_query_version_id: int,
    reviewer_user_id: int,
    comment: str | None = None,
) -> SqlQueryVersion:
    """PENDING → REJECTED."""
    version = _get_version_or_404(session, sql_query_version_id)
    if version.status != "PENDING":
        raise ConflictError(f"version {sql_query_version_id} is {version.status}, not PENDING")
    if version.submitted_by == reviewer_user_id:
        raise ValidationError("self-rejection is not allowed")

    version.status = "REJECTED"
    version.reviewed_by = reviewer_user_id
    version.reviewed_at = datetime.now(UTC)
    version.review_comment = comment
    session.flush()
    return version


def _get_version_or_404(session: Session, vid: int) -> SqlQueryVersion:
    v = session.get(SqlQueryVersion, vid)
    if v is None:
        raise NotFoundError(f"sql_query_version {vid} not found")
    return v


__all__ = [
    "DEFAULT_PREVIEW_LIMIT",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "ExplainResult",
    "PreviewResult",
    "ValidateOutcome",
    "add_version",
    "approve_version",
    "create_query",
    "explain",
    "preview",
    "reject_version",
    "submit_version",
    "validate_with_audit",
]
