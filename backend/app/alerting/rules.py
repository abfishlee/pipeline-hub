"""Phase 8.5 — Alert rule 정의.

각 rule 은 SQL 또는 endpoint 결과를 평가하고 임계 초과 시 alert payload 반환.
중복 발사 억제는 `dispatcher.py` 가 audit.alert_log 의 last fired_at 으로 처리.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class AlertPayload:
    rule_code: str
    severity: str  # INFO/WARN/ERROR/CRITICAL
    target_key: str | None
    title: str
    message: str
    metadata: dict[str, Any]


@dataclass
class AlertRule:
    code: str
    severity: str
    description: str
    cooldown_minutes: int  # 같은 (code, target_key) 는 N분 내 재발사 안 함
    evaluate: Callable[[Session], list[AlertPayload]]


# ---------------------------------------------------------------------------
# Rule 1 — Workflow 24h 실패율 30% 초과
# ---------------------------------------------------------------------------
def _rule_failure_rate(s: Session) -> list[AlertPayload]:
    since = datetime.utcnow() - timedelta(hours=24)
    rows = s.execute(
        text(
            """
            SELECT pr.workflow_id, w.name AS workflow_name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN pr.status='FAILED' THEN 1 ELSE 0 END) AS failed
              FROM run.pipeline_run pr
              LEFT JOIN wf.workflow_definition w
                     ON w.workflow_id = pr.workflow_id
             WHERE pr.started_at >= :since
             GROUP BY pr.workflow_id, w.name
            HAVING COUNT(*) >= 5
               AND SUM(CASE WHEN pr.status='FAILED' THEN 1 ELSE 0 END)::float8
                   / COUNT(*)::float8 > 0.3
            """
        ),
        {"since": since},
    ).all()
    out: list[AlertPayload] = []
    for r in rows:
        rate = float(r.failed) / float(r.total) * 100
        out.append(
            AlertPayload(
                rule_code="failure_rate_24h",
                severity="ERROR",
                target_key=f"workflow:{r.workflow_id}",
                title=f"실패율 임계 초과 — {r.workflow_name or f'workflow#{r.workflow_id}'}",
                message=(
                    f"24h 내 {int(r.total)}건 중 {int(r.failed)}건 실패 "
                    f"({rate:.1f}%, 임계 30%)"
                ),
                metadata={
                    "workflow_id": int(r.workflow_id),
                    "workflow_name": r.workflow_name,
                    "total": int(r.total),
                    "failed": int(r.failed),
                    "failure_rate_pct": round(rate, 2),
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Rule 2 — SLA Lag p95 > 180s
# ---------------------------------------------------------------------------
def _rule_sla_lag(s: Session) -> list[AlertPayload]:
    since = datetime.utcnow() - timedelta(hours=24)
    row = s.execute(
        text(
            """
            WITH lags AS (
              SELECT EXTRACT(EPOCH FROM (pr.finished_at - ie.received_at))
                       AS lag_sec
                FROM audit.inbound_event ie
                JOIN run.pipeline_run pr
                  ON pr.pipeline_run_id = ie.workflow_run_id
               WHERE ie.received_at >= :since
                 AND ie.workflow_run_id IS NOT NULL
                 AND pr.finished_at IS NOT NULL
                 AND pr.status = 'SUCCESS'
            )
            SELECT COUNT(*) AS n,
                   PERCENTILE_DISC(0.95) WITHIN GROUP (ORDER BY lag_sec) AS p95
              FROM lags
            """
        ),
        {"since": since},
    ).first()
    if row is None or (row.n or 0) < 5 or row.p95 is None:
        return []
    p95 = float(row.p95)
    if p95 <= 180:
        return []
    return [
        AlertPayload(
            rule_code="sla_lag_p95",
            severity="WARN",
            target_key="global",
            title="SLA Lag p95 > 180s",
            message=(
                f"24h 내 {int(row.n)}건 처리, p95 lag = {p95:.1f}초 "
                "(CLAUDE.md 목표: ≤ 60초)"
            ),
            metadata={"sample_count": int(row.n), "p95_seconds": round(p95, 1)},
        )
    ]


# ---------------------------------------------------------------------------
# Rule 3 — Channel Stale (60min 이상 inbound 미수신)
# ---------------------------------------------------------------------------
def _rule_channel_stale(s: Session) -> list[AlertPayload]:
    rows = s.execute(
        text(
            """
            SELECT c.channel_code, c.name AS channel_name,
                   MAX(ie.received_at) AS last_at
              FROM domain.inbound_channel c
              LEFT JOIN audit.inbound_event ie
                     ON ie.channel_code = c.channel_code
             WHERE c.is_active = true
               AND c.status = 'PUBLISHED'
             GROUP BY c.channel_code, c.name
            HAVING MAX(ie.received_at) IS NOT NULL
               AND MAX(ie.received_at) < (now() - INTERVAL '60 minutes')
            """
        )
    ).all()
    out: list[AlertPayload] = []
    for r in rows:
        out.append(
            AlertPayload(
                rule_code="channel_stale",
                severity="WARN",
                target_key=f"channel:{r.channel_code}",
                title=f"채널 데이터 끊김 — {r.channel_name or r.channel_code}",
                message=(
                    f"채널 {r.channel_code} 의 마지막 inbound 수신 시각은 "
                    f"{r.last_at} (60분 초과)"
                ),
                metadata={
                    "channel_code": str(r.channel_code),
                    "last_received_at": (
                        r.last_at.isoformat() if r.last_at else None
                    ),
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
RULES: list[AlertRule] = [
    AlertRule(
        code="failure_rate_24h",
        severity="ERROR",
        description="Workflow 24h 실패율 30% 초과",
        cooldown_minutes=30,
        evaluate=_rule_failure_rate,
    ),
    AlertRule(
        code="sla_lag_p95",
        severity="WARN",
        description="SLA Lag p95 > 180s",
        cooldown_minutes=15,
        evaluate=_rule_sla_lag,
    ),
    AlertRule(
        code="channel_stale",
        severity="WARN",
        description="채널 60min 이상 inbound 미수신",
        cooldown_minutes=60,
        evaluate=_rule_channel_stale,
    ),
]


__all__ = ["AlertRule", "AlertPayload", "RULES"]
