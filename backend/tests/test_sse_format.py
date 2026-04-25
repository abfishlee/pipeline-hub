"""Unit — SSE 포맷 헬퍼 (Phase 3.2.3).

`format_event` / `heartbeat_event` 의 직렬화 정합성 + multi-line data 처리.
"""

from __future__ import annotations

from app.core.sse import format_event, heartbeat_event


def test_format_event_basic_dict() -> None:
    out = format_event(event="node.state.changed", data={"k": 1, "v": "abc"})
    assert "event: node.state.changed" in out
    assert 'data: {"k":1,"v":"abc"}' in out
    assert out.endswith("\n\n")


def test_format_event_string_data_passthrough() -> None:
    out = format_event(event="open", data="hello")
    assert "event: open" in out
    assert "data: hello" in out


def test_format_event_multiline_string_splits_data_lines() -> None:
    out = format_event(event="logs", data="line1\nline2\nline3")
    assert out.count("data: ") == 3
    assert "data: line1" in out
    assert "data: line2" in out
    assert "data: line3" in out


def test_format_event_with_event_id() -> None:
    out = format_event(event="ping", data={}, event_id="42")
    assert "id: 42" in out
    assert "event: ping" in out


def test_format_event_none_data_renders_empty() -> None:
    out = format_event(event="ping", data=None)
    assert "data: " in out
    assert "event: ping" in out


def test_heartbeat_event_is_ping() -> None:
    out = heartbeat_event()
    assert "event: ping" in out
    assert out.endswith("\n\n")


def test_format_event_korean_unicode_preserved() -> None:
    out = format_event(event="msg", data={"k": "한글"})
    assert "한글" in out
