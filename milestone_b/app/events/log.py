"""Append-only event log — the spine of the slice (DESIGN_TIGHTENING.md section 1).

Every canonical record is created by appending an event; the task snapshot is a
fold over the event stream (`app.events.projections`).

Deviation from MILESTONE_B_PLAN.md section 4: the plan names "SQLite via SQLAlchemy
core". Day 1 uses the stdlib `sqlite3` module instead so the slice runs with no
third-party dependency beyond pydantic. The `EventLog` class is the seam; moving
to Postgres later is a localized change behind this interface.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class EventKind:
    REQUEST = "REQUEST"
    STATE = "STATE"
    CONTRACT = "CONTRACT"
    CLARIFICATION = "CLARIFICATION"
    PLAN = "PLAN"
    ACTION_PROPOSAL = "ACTION_PROPOSAL"
    POLICY_DECISION = "POLICY_DECISION"
    OBSERVATION = "OBSERVATION"
    ARTIFACT = "ARTIFACT"
    VERIFICATION = "VERIFICATION"
    MODEL_RUN = "MODEL_RUN"
    RESULT = "RESULT"
    ERROR = "ERROR"
    # Milestone C — security and authority
    CAPABILITY_GRANT = "CAPABILITY_GRANT"
    CAPABILITY_DENY = "CAPABILITY_DENY"
    APPROVAL_REQUEST = "APPROVAL_REQUEST"
    APPROVAL_DECISION = "APPROVAL_DECISION"
    EGRESS_BLOCKED = "EGRESS_BLOCKED"
    TAINT_BLOCKED = "TAINT_BLOCKED"
    # Milestone D — recovery and progress
    PROGRESS = "PROGRESS"
    CHECKPOINT = "CHECKPOINT"
    RECONCILE = "RECONCILE"
    BUDGET = "BUDGET"
    ESCALATION = "ESCALATION"
    # Milestone E — multi-agent coordination
    AGENT_MESSAGE = "AGENT_MESSAGE"
    CRITIC = "CRITIC"
    DISAGREEMENT = "DISAGREEMENT"
    ROLE_PERF = "ROLE_PERF"
    EVIDENCE = "EVIDENCE"
    COMPOSITION = "COMPOSITION"
    # Milestone F — memory and experience
    MEMORY = "MEMORY"
    EXPERIENCE = "EXPERIENCE"
    EXPERIENCE_TRANSITION = "EXPERIENCE_TRANSITION"

    ROUTE = "ROUTE"
    HARDWARE = "HARDWARE"

    EVAL = "EVAL"
    CANARY = "CANARY"
    REGRESSION = "REGRESSION"

    REPO = "REPO"
    IMPACT = "IMPACT"

    RESEARCH = "RESEARCH"
    SYNTHESIS = "SYNTHESIS"
    KB = "KB"
    AUTHORING = "AUTHORING"
    ENGINE = "ENGINE"
    SELECTION = "SELECTION"


class Event(BaseModel):
    seq: int = 0
    id: str
    task_id: str
    ts: float
    kind: str
    payload: dict[str, Any]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    id      TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    ts      REAL NOT NULL,
    kind    TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_task ON events (task_id, seq);
"""


class EventLog:
    """Append-only. No update or delete path by design."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def append(self, task_id: str, kind: str, payload: dict[str, Any] | BaseModel) -> Event:
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        elif not isinstance(payload, dict):
            raise TypeError(f"payload must be a dict or BaseModel, got {type(payload)!r}")
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        ts = time.time()
        cur = self._conn.execute(
            "INSERT INTO events (id, task_id, ts, kind, payload) VALUES (?, ?, ?, ?, ?)",
            (event_id, task_id, ts, kind, json.dumps(payload)),
        )
        self._conn.commit()
        return Event(
            seq=int(cur.lastrowid or 0),
            id=event_id,
            task_id=task_id,
            ts=ts,
            kind=kind,
            payload=payload,
        )

    def read(self, task_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT seq, id, task_id, ts, kind, payload FROM events "
            "WHERE task_id = ? ORDER BY seq",
            (task_id,),
        ).fetchall()
        return [self._to_event(r) for r in rows]

    def all(self) -> list[Event]:
        rows = self._conn.execute(
            "SELECT seq, id, task_id, ts, kind, payload FROM events ORDER BY seq"
        ).fetchall()
        return [self._to_event(r) for r in rows]

    def task_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT task_id FROM events GROUP BY task_id ORDER BY MIN(seq)"
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _to_event(row: tuple) -> Event:
        return Event(
            seq=row[0],
            id=row[1],
            task_id=row[2],
            ts=row[3],
            kind=row[4],
            payload=json.loads(row[5]),
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
