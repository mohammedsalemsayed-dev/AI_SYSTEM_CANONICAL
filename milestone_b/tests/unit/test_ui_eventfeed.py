"""Acceptance (Unit): the SSE event feed tails the append-only log by seq
(MILESTONE_H_PLAN.md §6)."""

from __future__ import annotations

import json

from app.events.log import EventKind, EventLog
from app.ui.events import EventFeed, keepalive_frame, sse_frame


def test_feed_yields_only_new_rows_and_advances() -> None:
    log = EventLog()
    log.append("t1", EventKind.REQUEST, {"text": "a"})
    feed = EventFeed(log)
    first = feed.poll()
    assert [e.kind for e in first] == ["REQUEST"]
    assert feed.poll() == []  # nothing new
    log.append("t1", EventKind.STATE, {"state": "INTERPRETING"})
    second = feed.poll()
    assert [e.kind for e in second] == ["STATE"]
    assert feed.cursor == second[0].seq


def test_feed_resumes_from_since_seq() -> None:
    log = EventLog()
    e1 = log.append("t1", EventKind.REQUEST, {"text": "a"})
    log.append("t1", EventKind.STATE, {"state": "INTERPRETING"})
    feed = EventFeed(log, since_seq=e1.seq)
    assert [e.kind for e in feed.poll()] == ["STATE"]  # strictly after e1


def test_feed_task_filter() -> None:
    log = EventLog()
    log.append("t1", EventKind.REQUEST, {"text": "a"})
    log.append("t2", EventKind.REQUEST, {"text": "b"})
    feed = EventFeed(log, task_id="t2")
    rows = feed.poll()
    assert [e.task_id for e in rows] == ["t2"]
    # cursor still advanced past the filtered-out row
    assert feed.poll() == []


def test_sse_frame_is_valid() -> None:
    log = EventLog()
    e = log.append("t1", EventKind.STATE, {"state": "PLANNING"})
    frame = sse_frame(e)
    assert frame.startswith(f"id: {e.seq}\n")
    assert "event: STATE\n" in frame and frame.endswith("\n\n")
    data_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0]
    parsed = json.loads(data_line[len("data: "):])
    assert parsed["kind"] == "STATE" and parsed["payload"] == {"state": "PLANNING"}
    assert keepalive_frame() == ": keep-alive\n\n"
