"""Notify worker (Phase 4.2.2) — outbox `notify.requested` / `pipeline_run.on_hold` /
`pipeline_run.hold_*` 이벤트를 Slack/Email 로 발송.

흐름:
  1. `dispatch_pending_notifications.send()` 가 enqueue 되면 outbox 에서 PENDING
     상태의 알림 후보 (event_type IN (...)) 를 1배치 가져와 발송 시도.
  2. 성공 시 outbox row 의 status='PUBLISHED', published_at=now().
  3. 실패 시 attempt_no++ + last_error 기록. attempt_no >= settings.outbox_max_attempts
     이면 dead_letter 로 이동 (publisher 와 동일 정책).

설계:
  - Slack 은 webhook URL 호출 (`notify_slack_webhook_url` 비어 있으면 no-op + 로그).
  - Email 은 Phase 4.2.2 시점에 stub — 로그만 남기고 PUBLISHED 마킹.
  - HTTP 호출은 stdlib `urllib` 사용 — 의존성 추가 없이 작은 페이로드 발송.
"""

from __future__ import annotations

import contextlib
import json
import logging
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from app.config import get_settings
from app.models.run import DeadLetter, EventOutbox
from app.workers import pipeline_actor

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

NOTIFY_EVENT_TYPES = (
    "notify.requested",
    "pipeline_run.on_hold",
    "pipeline_run.hold_approved",
    "pipeline_run.hold_rejected",
)
BATCH_SIZE = 50


def _send_slack(webhook_url: str, text: str, timeout_sec: float) -> None:
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"slack webhook returned {resp.status}")


def _format_message(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "pipeline_run.on_hold":
        return (
            f":warning: *Pipeline ON_HOLD* — run #{payload.get('pipeline_run_id')} "
            f"(workflow {payload.get('workflow_id')}, node `{payload.get('node_key')}`)\n"
            f"reason: {payload.get('error_message') or 'DQ check failed'}"
        )
    if event_type == "pipeline_run.hold_approved":
        return (
            f":white_check_mark: *Pipeline RESUMED* — run #{payload.get('pipeline_run_id')} "
            f"approved by user_id={payload.get('signer_user_id')}"
        )
    if event_type == "pipeline_run.hold_rejected":
        return (
            f":x: *Pipeline REJECTED* — run #{payload.get('pipeline_run_id')} cancelled by "
            f"user_id={payload.get('signer_user_id')}, "
            f"rollback_rows={payload.get('rollback_rows', 0)}"
        )
    if event_type == "notify.requested":
        subject = payload.get("subject") or ""
        body = payload.get("body") or ""
        level = payload.get("level") or "INFO"
        return f"[{level}] {subject}\n{body}".strip()
    return f"{event_type}: {json.dumps(payload, default=str)[:500]}"


def _dispatch(payload: dict[str, Any], event_type: str) -> None:
    """채널별 디스패치. 실패 시 raise — 호출자가 attempt_no++."""
    settings = get_settings()
    text = _format_message(event_type, payload)
    target_channel = str(payload.get("channel") or "slack").lower()
    target = str(payload.get("target") or "").strip()

    if target_channel == "slack":
        webhook = target if target.startswith("http") else (
            settings.notify_slack_webhook_url.get_secret_value()
        )
        if not webhook:
            logger.info(
                "slack webhook not configured; logging notify-only event_type=%s", event_type
            )
            return
        _send_slack(webhook, text, settings.notify_http_timeout_sec)
    elif target_channel == "webhook":
        if not target.startswith("http"):
            raise ValueError(f"webhook target must be URL: {target!r}")
        _send_slack(target, text, settings.notify_http_timeout_sec)
    elif target_channel == "email":
        # Phase 4.2.2 stub — 로그만. Phase 4.x 후속에서 NCP Mailer 도입.
        logger.info(
            "email stub: from=%s to=%s subject=%s",
            settings.notify_email_from,
            target or "(none)",
            payload.get("subject"),
        )
    else:
        raise ValueError(f"unknown notify channel: {target_channel!r}")


def _process_event(session: Session, event: EventOutbox) -> None:
    payload = dict(event.payload_json or {})
    try:
        _dispatch(payload, event.event_type)
    except (urllib.error.URLError, RuntimeError, ValueError, OSError) as exc:
        event.attempt_no += 1
        event.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        settings = get_settings()
        if event.attempt_no >= settings.outbox_max_attempts:
            event.status = "FAILED"
            session.add(
                DeadLetter(
                    origin="notify_worker",
                    payload_json={
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "payload": payload,
                    },
                    error_message=event.last_error,
                )
            )
        return

    event.status = "PUBLISHED"
    event.last_error = None
    from datetime import UTC, datetime  # local import — small footprint.

    event.published_at = datetime.now(UTC)


@pipeline_actor(queue_name="notify", max_retries=2, time_limit=30_000)
def dispatch_pending_notifications() -> dict[str, int]:
    """outbox 에서 알림 후보 1배치 처리. result = {selected, sent, failed}."""
    from app.db.sync_session import get_sync_sessionmaker

    sm = get_sync_sessionmaker()
    selected = sent = failed = 0
    with sm() as session:
        # 비관적 락 — 동시 worker 다수일 때 같은 row 중복 발송 방지.
        rows = list(
            session.execute(
                select(EventOutbox)
                .where(EventOutbox.status == "PENDING")
                .where(EventOutbox.event_type.in_(NOTIFY_EVENT_TYPES))
                .order_by(EventOutbox.event_id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        selected = len(rows)
        for ev in rows:
            before = ev.status
            with contextlib.suppress(Exception):
                _process_event(session, ev)
            if ev.status == "PUBLISHED" and before != "PUBLISHED":
                sent += 1
            elif ev.status == "FAILED":
                failed += 1
        session.commit()

    return {"selected": selected, "sent": sent, "failed": failed}


def consume_pending_notifications_for_test(session: Session) -> dict[str, int]:
    """Test 헬퍼 — actor enqueue 없이 직접 발송 처리."""
    selected = sent = failed = 0
    rows = list(
        session.execute(
            select(EventOutbox)
            .where(EventOutbox.status == "PENDING")
            .where(EventOutbox.event_type.in_(NOTIFY_EVENT_TYPES))
            .order_by(EventOutbox.event_id)
        )
        .scalars()
        .all()
    )
    selected = len(rows)
    for ev in rows:
        before = ev.status
        with contextlib.suppress(Exception):
            _process_event(session, ev)
        if ev.status == "PUBLISHED" and before != "PUBLISHED":
            sent += 1
        elif ev.status == "FAILED":
            failed += 1
    return {"selected": selected, "sent": sent, "failed": failed}


def reset_published_for_test(session: Session) -> int:
    """Test 헬퍼 — 모든 PUBLISHED notify 이벤트를 PENDING 으로 되돌림."""
    res = session.execute(
        update(EventOutbox)
        .where(EventOutbox.event_type.in_(NOTIFY_EVENT_TYPES))
        .where(EventOutbox.status == "PUBLISHED")
        .values(status="PENDING", published_at=None)
    )
    return int(getattr(res, "rowcount", 0) or 0)


__all__ = [
    "BATCH_SIZE",
    "NOTIFY_EVENT_TYPES",
    "consume_pending_notifications_for_test",
    "dispatch_pending_notifications",
    "reset_published_for_test",
]
