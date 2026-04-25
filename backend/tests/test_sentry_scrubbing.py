"""Sentry before_send PII 스크럽 단위 테스트.

Sentry 자체를 실 호출하지 않고 `_scrub_event` 만 직접 검증 — 운영 사고 방지를 위한
회귀.
"""

from __future__ import annotations

from app.core.sentry import _scrub_event


def test_scrub_replaces_sensitive_request_headers() -> None:
    event = {
        "request": {
            "url": "http://localhost:8000/v1/auth/login",
            "method": "POST",
            "headers": {
                "Authorization": "Bearer xxx",
                "X-OCR-SECRET": "shhh",
                "X-API-Key": "key-1",
                "Cookie": "session=abc",
                "User-Agent": "curl/8.0",
                "Content-Type": "application/json",
            },
        },
    }
    out = _scrub_event(event, {})
    assert out is not None
    headers = out["request"]["headers"]
    assert headers["Authorization"] == "[Filtered]"
    assert headers["X-OCR-SECRET"] == "[Filtered]"
    assert headers["X-API-Key"] == "[Filtered]"
    assert headers["Cookie"] == "[Filtered]"
    # 정상 헤더는 그대로 유지.
    assert headers["User-Agent"] == "curl/8.0"
    assert headers["Content-Type"] == "application/json"


def test_scrub_replaces_sensitive_body_keys_in_request_data() -> None:
    event = {
        "request": {
            "data": {
                "login_id": "admin",
                "password": "p@ssw0rd",
                "api_key": "secret",
                "token": "jwt-...",
                "memo": "ok",
            },
        },
    }
    out = _scrub_event(event, {})
    assert out is not None
    data = out["request"]["data"]
    assert data["password"] == "[Filtered]"
    assert data["api_key"] == "[Filtered]"
    assert data["token"] == "[Filtered]"
    assert data["login_id"] == "admin"
    assert data["memo"] == "ok"


def test_scrub_handles_nested_extra() -> None:
    event = {
        "extra": {
            "config": {
                "user": "app",
                "password": "supersecret",
                "host": "db",
            },
            "trace_id": "abc",
        },
    }
    out = _scrub_event(event, {})
    assert out is not None
    assert out["extra"]["config"]["password"] == "[Filtered]"
    assert out["extra"]["config"]["user"] == "app"
    assert out["extra"]["config"]["host"] == "db"
    assert out["extra"]["trace_id"] == "abc"


def test_scrub_is_case_insensitive_for_sensitive_keys() -> None:
    event = {
        "request": {
            "headers": {
                "authorization": "Bearer y",
                "X-Ocr-Secret": "z",
            },
            "data": {"PASSWORD": "p", "Api_Key": "k"},
        }
    }
    out = _scrub_event(event, {})
    assert out is not None
    assert out["request"]["headers"]["authorization"] == "[Filtered]"
    assert out["request"]["headers"]["X-Ocr-Secret"] == "[Filtered]"
    assert out["request"]["data"]["PASSWORD"] == "[Filtered]"
    assert out["request"]["data"]["Api_Key"] == "[Filtered]"


def test_scrub_event_without_request_or_extra_is_safe() -> None:
    event = {"message": "boom", "level": "error"}
    out = _scrub_event(event, {})
    assert out == {"message": "boom", "level": "error"}


def test_scrub_string_body_is_left_untouched() -> None:
    """JSON 외 form/string body 는 dict 가 아니라 통째로 보관 — caller 가 별도 처리."""
    event = {
        "request": {
            "data": "username=admin&password=topsecret",
        }
    }
    out = _scrub_event(event, {})
    assert out is not None
    # 문자열은 그대로 (dict 가 아니라 mapping scrub 대상이 아님).
    # → 운영자는 send_default_pii=False + form body 미수집을 신뢰. 추후 string body 도
    # 패턴 마스킹이 필요하면 별도 유틸 추가.
    assert isinstance(out["request"]["data"], str)
