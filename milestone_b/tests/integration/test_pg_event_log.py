"""Acceptance (Integration): the Postgres event store is interface-parity with
`EventLog` and durable across reconnects.

Skipped unless NEXUS_PG_TEST_DSN points at a reachable database, e.g.
    NEXUS_PG_TEST_DSN=postgres://nexus:nexus@localhost:5433/nexus
The CI/dev default (no DSN) still runs on stdlib SQLite.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.events.log import EventKind, EventLog, open_event_log

_DSN = os.environ.get("NEXUS_PG_TEST_DSN")
pytestmark = pytest.mark.skipif(not _DSN, reason="set NEXUS_PG_TEST_DSN to run the Postgres tests")


@pytest.fixture
def pglog():
    psycopg = pytest.importorskip("psycopg")
    # each test gets its own table-truncated view; the schema is shared
    log = open_event_log(_DSN)
    with psycopg.connect(_DSN, autocommit=True) as c:
        c.execute("TRUNCATE events RESTART IDENTITY")
    yield log
    log.close()


def test_factory_picks_postgres_for_a_url(pglog) -> None:
    from app.events.pg_log import PostgresEventLog

    assert isinstance(pglog, PostgresEventLog)
    assert not isinstance(pglog, EventLog)


def test_append_read_all_task_ids_match_eventlog_semantics(pglog) -> None:
    e1 = pglog.append("t1", EventKind.REQUEST, {"text": "hi", "n": 1})
    e2 = pglog.append("t1", EventKind.STATE, {"state": "PLANNING"})
    e3 = pglog.append("t2", EventKind.RESULT, {"ok": True})

    assert (e1.seq, e2.seq, e3.seq) == (1, 2, 3)
    assert e1.id.startswith("evt_") and e1.ts > 0

    t1 = pglog.read("t1")
    assert [e.kind for e in t1] == ["REQUEST", "STATE"]
    assert t1[0].payload == {"text": "hi", "n": 1}  # jsonb round-trip -> dict
    assert [e.seq for e in pglog.all()] == [1, 2, 3]
    assert pglog.task_ids() == ["t1", "t2"]


def test_accepts_a_pydantic_model_payload(pglog) -> None:
    from app.schemas.contracts import TaskResult

    r = TaskResult(task_id="tX", state="COMPLETED", verified=True, summary="ok")
    ev = pglog.append("tX", EventKind.RESULT, r)
    assert ev.payload["state"] == "COMPLETED" and ev.payload["verified"] is True
    assert pglog.read("tX")[0].payload["summary"] == "ok"


def test_rejects_a_bad_payload_type(pglog) -> None:
    with pytest.raises(TypeError):
        pglog.append("t", EventKind.STATE, "not a dict")  # type: ignore[arg-type]


def test_durable_across_reconnect(pglog) -> None:
    tid = f"t_{uuid.uuid4().hex[:6]}"
    pglog.append(tid, EventKind.REQUEST, {"a": 1})
    pglog.append(tid, EventKind.STATE, {"state": "EXECUTING"})
    pglog.close()

    reopened = open_event_log(_DSN)
    try:
        got = reopened.read(tid)
        assert [e.kind for e in got] == ["REQUEST", "STATE"]
    finally:
        reopened.close()


def test_projection_folds_a_postgres_stream(pglog) -> None:
    from app.events.projections import project_task
    from app.schemas.contracts import TaskContract

    c = TaskContract(
        task_id="p1", original_request="fix add", objective="make add a+b",
        task_class="code_edit_local", success_criteria=["x"],
        required_evidence=["T0: pytest test_calc.py passes"],
    )
    pglog.append("p1", EventKind.REQUEST, {"text": "fix add", "workspace_path": "/ws"})
    pglog.append("p1", EventKind.STATE, {"state": "INTERPRETING"})
    pglog.append("p1", EventKind.CONTRACT, c.model_dump(mode="json"))
    pglog.append("p1", EventKind.STATE, {"state": "PLANNING"})

    snap = project_task(pglog.read("p1"))
    assert snap.state.value == "PLANNING" and snap.contract.objective == "make add a+b"
