"""PostgreSQL-backed event log — the durable, multi-session store behind the
same seam as `EventLog` (design-notes §1; MILESTONE_A_PLAN.md).

Identical public surface to `app.events.log.EventLog`: `append`, `read`, `all`,
`task_ids`, `close`, context manager, same `Event` rows. The only new dependency
is `psycopg` (v3), lazily imported so a SQLite-only install never needs it.

Schema is created on first connect (`CREATE TABLE IF NOT EXISTS`) — good enough
for the slice; a real migration tool (Alembic) drops in later without touching
callers. Append-only: no UPDATE / DELETE path, matching `EventLog`.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel

from app.events.log import Event  # reuse the exact row model

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq     BIGSERIAL PRIMARY KEY,
    id      TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    ts      DOUBLE PRECISION NOT NULL,
    kind    TEXT NOT NULL,
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_task ON events (task_id, seq);
"""


class PostgresEventLog:
    """Append-only Postgres event log. Same interface as `EventLog`."""

    def __init__(self, dsn: str) -> None:
        import psycopg  # lazy — only when a postgres URL is actually used

        self.dsn = dsn
        self._conn = psycopg.connect(dsn, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)

    # -- write --------------------------------------------------- #
    def append(self, task_id: str, kind: str, payload: dict[str, Any] | BaseModel) -> Event:
        from psycopg.types.json import Jsonb

        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        elif not isinstance(payload, dict):
            raise TypeError(f"payload must be a dict or BaseModel, got {type(payload)!r}")
        event_id = f"evt_{uuid.uuid4().hex[:12]}"
        ts = time.time()
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO events (id, task_id, ts, kind, payload) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING seq",
                (event_id, task_id, ts, kind, Jsonb(payload)),
            )
            seq = int(cur.fetchone()[0])
        return Event(seq=seq, id=event_id, task_id=task_id, ts=ts, kind=kind, payload=payload)

    # -- read ---------------------------------------------------- #
    def read(self, task_id: str) -> list[Event]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT seq, id, task_id, ts, kind, payload FROM events "
                "WHERE task_id = %s ORDER BY seq",
                (task_id,),
            )
            return [self._row(r) for r in cur.fetchall()]

    def all(self) -> list[Event]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT seq, id, task_id, ts, kind, payload FROM events ORDER BY seq")
            return [self._row(r) for r in cur.fetchall()]

    def task_ids(self) -> list[str]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT task_id FROM events GROUP BY task_id ORDER BY MIN(seq)")
            return [r[0] for r in cur.fetchall()]

    @staticmethod
    def _row(r: tuple) -> Event:
        # psycopg decodes JSONB straight to a dict
        return Event(seq=r[0], id=r[1], task_id=r[2], ts=r[3], kind=r[4], payload=r[5])

    # -- lifecycle --------------------------------------------- #
    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "PostgresEventLog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
