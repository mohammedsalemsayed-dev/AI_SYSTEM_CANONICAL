"""Event feed for the SSE stream (MILESTONE_H_PLAN.md §2).

The event log is append-only with a monotonic `seq`, so tailing is just
`SELECT ... WHERE seq > :last`. `EventFeed` holds a cursor and yields new rows;
`sse_frame` formats one Server-Sent-Events frame.
"""

from __future__ import annotations

import json
from typing import Iterator

from app.events.log import Event, EventLog


class EventFeed:
    def __init__(self, log: EventLog, *, task_id: str | None = None, since_seq: int = 0) -> None:
        self._log = log
        self._task_id = task_id
        self._cursor = since_seq

    @property
    def cursor(self) -> int:
        return self._cursor

    def poll(self) -> list[Event]:
        """Return every event after the cursor (optionally filtered to one task),
        advancing the cursor. Empty list when there is nothing new."""
        rows = self._log._conn.execute(  # noqa: SLF001 — same package, read-only tail
            "SELECT seq, id, task_id, ts, kind, payload FROM events "
            "WHERE seq > ? ORDER BY seq",
            (self._cursor,),
        ).fetchall()
        out: list[Event] = []
        for r in rows:
            self._cursor = max(self._cursor, r[0])
            if self._task_id is not None and r[2] != self._task_id:
                continue
            out.append(
                Event(seq=r[0], id=r[1], task_id=r[2], ts=r[3], kind=r[4],
                      payload=json.loads(r[5]))
            )
        return out

    def frames(self) -> Iterator[str]:
        for e in self.poll():
            yield sse_frame(e)


def sse_frame(event: Event) -> str:
    data = json.dumps(
        {
            "seq": event.seq, "id": event.id, "task_id": event.task_id,
            "ts": event.ts, "kind": event.kind, "payload": event.payload,
        }
    )
    return f"id: {event.seq}\nevent: {event.kind}\ndata: {data}\n\n"


def keepalive_frame() -> str:
    return ": keep-alive\n\n"
