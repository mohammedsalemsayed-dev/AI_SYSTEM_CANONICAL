"""MemoryStore — hierarchical memory over SQLite (MILESTONE_F_PLAN.md §2, §7.4).

Append-mostly. Supersession is by writing a new version and setting
`superseded_by` on the old row — never deletion (except the STALE-experience
hard-delete after 180 days, which is a separate maintenance call).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from app.schemas.contracts import MemoryRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    id           TEXT NOT NULL UNIQUE,
    task_id      TEXT NOT NULL DEFAULT '',
    tier         TEXT NOT NULL,
    kind         TEXT NOT NULL,
    content      TEXT NOT NULL,
    scope        TEXT NOT NULL DEFAULT 'global',
    trust        TEXT NOT NULL DEFAULT 'workspace',
    version      INTEGER NOT NULL DEFAULT 1,
    ts           REAL NOT NULL,
    superseded_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_memory_tier ON memory (tier, scope);
"""

_STALE_MAX_AGE_S = 180 * 24 * 3600


class MemoryStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def put(self, record: MemoryRecord) -> MemoryRecord:
        self._conn.execute(
            "INSERT INTO memory (id, task_id, tier, kind, content, scope, trust, "
            "version, ts, superseded_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                record.id, record.task_id, record.tier, record.kind, record.content,
                record.scope, record.trust, record.version, record.ts, record.superseded_by,
            ),
        )
        self._conn.commit()
        return record

    def supersede(self, old_id: str, new: MemoryRecord) -> MemoryRecord:
        new.version = self._version_of(old_id) + 1
        self.put(new)
        self._conn.execute(
            "UPDATE memory SET superseded_by=? WHERE id=?", (new.id, old_id)
        )
        self._conn.commit()
        return new

    def all(self, *, tier: str | None = None, include_superseded: bool = False) -> list[MemoryRecord]:
        q = "SELECT id, task_id, tier, kind, content, scope, trust, version, ts, superseded_by FROM memory"
        conds, args = [], []
        if tier:
            conds.append("tier=?")
            args.append(tier)
        if not include_superseded:
            conds.append("superseded_by IS NULL")
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY seq"
        return [self._row(r) for r in self._conn.execute(q, args).fetchall()]

    def drop_stale_experience_pointers(self, now: float | None = None) -> int:
        """Hard-delete `role_perf`/experience-pointer rows older than 180 days that
        are already superseded (STALE-cleanup, §7.4). Experience records themselves
        live in the ExperienceStore."""
        ref = now if now is not None else time.time()
        cur = self._conn.execute(
            "DELETE FROM memory WHERE superseded_by IS NOT NULL AND ts < ?",
            (ref - _STALE_MAX_AGE_S,),
        )
        self._conn.commit()
        return cur.rowcount

    def _version_of(self, mem_id: str) -> int:
        row = self._conn.execute(
            "SELECT version FROM memory WHERE id=?", (mem_id,)
        ).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row(r: tuple) -> MemoryRecord:
        return MemoryRecord(
            id=r[0], task_id=r[1], tier=r[2], kind=r[3], content=r[4],
            scope=r[5], trust=r[6], version=r[7], ts=r[8], superseded_by=r[9],
        )

    def close(self) -> None:
        self._conn.close()

    # convenience helpers -------------------------------------------- #
    def record_role_perf(self, role: str, task_class: str, payload: dict) -> MemoryRecord:
        return self.put(
            MemoryRecord(
                tier="system", kind="role_perf", scope=f"{role}:{task_class}",
                content=json.dumps(payload), trust="workspace",
            )
        )

    def latest_role_perf(self, role: str, task_class: str) -> dict | None:
        rows = [
            m for m in self.all(tier="system")
            if m.kind == "role_perf" and m.scope == f"{role}:{task_class}"
        ]
        return json.loads(rows[-1].content) if rows else None
