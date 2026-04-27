"""Phase 8.5 — Alert dispatcher (Slack webhook + audit.alert_log).

flow:
  1. evaluate_and_fire_rules(): RULES 순회, 각 rule 평가
  2. cooldown 체크 (audit.alert_log 의 last fired_at 비교)
  3. dispatch_alert(): Slack webhook (env 있으면) 또는 log fallback
  4. audit.alert_log INSERT
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.alerting.rules import RULES, AlertPayload

logger = logging.getLogger(__name__)


def _slack_webhook_url() -> str | None:
    return os.getenv("ALERT_SLACK_WEBHOOK_URL") or None


def _is_in_cooldown(
    s: Session, rule_code: str, target_key: str | None, cooldown_minutes: int
) -> bool:
    cutoff = datetime.utcnow() - timedelta(minutes=cooldown_minutes)
    row = s.execute(
        text(
            """
            SELECT 1 FROM audit.alert_log
             WHERE rule_code = :rc
               AND COALESCE(target_key,'') = COALESCE(:tk,'')
               AND fired_at >= :cutoff
             LIMIT 1
            """
        ),
        {"rc": rule_code, "tk": target_key, "cutoff": cutoff},
    ).first()
    return row is not None


def _send_slack(webhook: str, payload: AlertPayload) -> tuple[bool, str | None]:
    """Slack incoming webhook — best-effort, 짧은 timeout."""
    color = {
        "INFO": "#3498db",
        "WARN": "#f39c12",
        "ERROR": "#e74c3c",
        "CRITICAL": "#8e44ad",
    }.get(payload.severity, "#95a5a6")
    body = {
        "attachments": [
            {
                "color": color,
                "title": f"[{payload.severity}] {payload.title}",
                "text": payload.message,
                "fields": [
                    {"title": "rule", "value": payload.rule_code, "short": True},
                    {"title": "target", "value": payload.target_key or "—", "short": True},
                ],
                "footer": "datapipeline alerting · Phase 8.5",
                "ts": int(datetime.utcnow().timestamp()),
            }
        ]
    }
    try:
        r = httpx.post(webhook, json=body, timeout=5.0)
        if r.status_code >= 300:
            return False, f"slack {r.status_code}: {r.text[:200]}"
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def dispatch_alert(s: Session, payload: AlertPayload) -> dict[str, Any]:
    """Alert 1건 발사 + audit.alert_log INSERT."""
    webhook = _slack_webhook_url()
    channel = "slack" if webhook else "log"
    delivered = False
    delivery_error: str | None = None

    if webhook:
        delivered, delivery_error = _send_slack(webhook, payload)
        if not delivered:
            logger.warning(
                "alert.slack_failed",
                extra={
                    "rule_code": payload.rule_code,
                    "target_key": payload.target_key,
                    "error": delivery_error,
                },
            )
    else:
        logger.warning(
            "alert.fired (log channel)",
            extra={
                "rule_code": payload.rule_code,
                "severity": payload.severity,
                "target_key": payload.target_key,
                "title": payload.title,
                "message": payload.message,
            },
        )
        delivered = True  # log channel 은 무조건 성공

    s.execute(
        text(
            """
            INSERT INTO audit.alert_log
              (rule_code, severity, target_key, title, message,
               metadata, channel, delivered, delivery_error)
            VALUES (:rc, :sv, :tk, :ti, :msg,
                    CAST(:meta AS JSONB), :ch, :d, :de)
            """
        ),
        {
            "rc": payload.rule_code,
            "sv": payload.severity,
            "tk": payload.target_key,
            "ti": payload.title,
            "msg": payload.message,
            "meta": json.dumps(payload.metadata),
            "ch": channel,
            "d": delivered,
            "de": delivery_error,
        },
    )
    return {
        "rule_code": payload.rule_code,
        "delivered": delivered,
        "channel": channel,
        "error": delivery_error,
    }


def evaluate_and_fire_rules(s: Session) -> list[dict[str, Any]]:
    """모든 RULES 평가 → cooldown 통과 시 dispatch_alert."""
    fired: list[dict[str, Any]] = []
    for rule in RULES:
        try:
            payloads = rule.evaluate(s)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "alert.rule_eval_failed",
                extra={"rule_code": rule.code, "error": str(exc)},
            )
            continue
        for payload in payloads:
            if _is_in_cooldown(s, payload.rule_code, payload.target_key, rule.cooldown_minutes):
                continue
            result = dispatch_alert(s, payload)
            fired.append(result)
    return fired


__all__ = ["dispatch_alert", "evaluate_and_fire_rules"]
