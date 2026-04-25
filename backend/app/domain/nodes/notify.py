"""NOTIFY 노드 — outbox(`notify.requested`) 적재.

Phase 3.2.2 한정으로 outbox 만 발행. 실 Slack/Email 호출은 Phase 4 에서 별도
worker (`notify_worker`) 가 outbox stream 을 소비.

config:
  - `channel`: 'slack' | 'email' | 'webhook' (필수)
  - `target`: webhook URL 또는 채널 식별자 (예: `#alerts`, `ops@example.com`)
  - `level`: 'INFO' | 'WARN' | 'ERROR' (기본 INFO)
  - `subject`: 메시지 제목 (선택)
  - `body`: 본문 (필수)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domain.nodes import NodeContext, NodeError, NodeOutput
from app.models.run import EventOutbox

name = "NOTIFY"

_ALLOWED_CHANNELS = frozenset({"slack", "email", "webhook"})
_ALLOWED_LEVELS = frozenset({"INFO", "WARN", "ERROR"})


def run(context: NodeContext, config: Mapping[str, Any]) -> NodeOutput:
    channel = str(config.get("channel") or "").lower()
    if channel not in _ALLOWED_CHANNELS:
        raise NodeError(f"channel must be one of {sorted(_ALLOWED_CHANNELS)} (got {channel!r})")
    target = str(config.get("target") or "").strip()
    if not target:
        raise NodeError("`target` is required")
    level = str(config.get("level") or "INFO").upper()
    if level not in _ALLOWED_LEVELS:
        raise NodeError(f"level must be one of {sorted(_ALLOWED_LEVELS)}")
    body = str(config.get("body") or "").strip()
    if not body:
        raise NodeError("`body` is required")
    subject = str(config.get("subject") or "")[:200]

    payload = {
        "channel": channel,
        "target": target,
        "level": level,
        "subject": subject,
        "body": body[:4000],
        "pipeline_run_id": context.pipeline_run_id,
        "node_run_id": context.node_run_id,
        "node_key": context.node_key,
    }

    context.session.add(
        EventOutbox(
            aggregate_type="pipeline_run",
            aggregate_id=str(context.pipeline_run_id),
            event_type="notify.requested",
            payload_json=payload,
        )
    )
    context.session.flush()

    return NodeOutput(
        status="success",
        row_count=1,
        payload={
            "channel": channel,
            "target": target,
            "level": level,
            "queued": True,
        },
    )


__all__ = ["name", "run"]
