"""Phase 8.5 — System Alert 채널.

규칙 기반 alert 평가 + Slack webhook 전송 + audit.alert_log 기록.

env:
  ALERT_SLACK_WEBHOOK_URL: 미설정 시 log fallback (delivered=False, channel='log')
"""

from app.alerting.dispatcher import dispatch_alert, evaluate_and_fire_rules
from app.alerting.rules import RULES, AlertRule

__all__ = ["dispatch_alert", "evaluate_and_fire_rules", "RULES", "AlertRule"]
