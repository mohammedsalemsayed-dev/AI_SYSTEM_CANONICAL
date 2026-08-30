"""ArtifactStore (MILESTONE_P_PLAN.md §2, design-notes §11.3).

Content-addressed blob store (sha-256, dedup) + a `version` chain per
`logical_key`. Canonical: `archive_before` marks, never deletes. Text kinds get a
`diff_versions` helper.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from app.services.artifacts.ref import ArtifactRef

MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_TEXT_KINDS = {"diff", "research_answer", "kb_answer", "document"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS blob (
    sha   TEXT PRIMARY KEY,
    bytes INTEGER NOT NULL,
    kind  TEXT NOT NULL,
    data  BLOB NOT NULL,
    ts    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS version (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    id          TEXT NOT NULL UNIQUE,
    logical_key TEXT NOT NULL,
    kind        TEXT NOT NULL,
    sha         TEXT NOT NULL,
    task_id     TEXT NOT NULL DEFAULT '',
    parent_id   TEXT,
    trust       TEXT NOT NULL DEFAULT 'workspace',
    truncated   INTEGER NOT NULL DEFAULT 0,
    archived    INTEGER NOT NULL DEFAULT 0,
    meta        TEXT NOT NULL DEFAULT '{}',
    ts          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_version_key ON version (logical_key, seq);
"""


class ArtifactStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        # check_same_thread=False: the desktop shell reads the store from its
        # request threads while the orchestrator writes from the main thread.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- write ------------------------------------------------ #
    def put(
        self,
        kind: str,
        content: str | bytes,
        *,
        task_id: str = "",
        logical_key: str = "",
        parent_id: str | None = None,
        trust: str = "workspace",
        meta: dict | None = None,
    ) -> ArtifactRef:
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        truncated = len(raw) > MAX_ARTIFACT_BYTES
        if truncated:
            raw = raw[:MAX_ARTIFACT_BYTES]
        sha = hashlib.sha256(raw).hexdigest()

        self._conn.execute(
            "INSERT OR IGNORE INTO blob (sha, bytes, kind, data, ts) VALUES (?,?,?,?,?)",
            (sha, len(raw), kind, raw, time.time()),
        )

        if parent_id is None and logical_key:
            prev = self.latest_for(logical_key)
            parent_id = prev.id if prev else None

        # idempotent on (logical_key, sha, task_id) — a resume must not duplicate
        existing = self._conn.execute(
            "SELECT id FROM version WHERE logical_key=? AND sha=? AND task_id=?",
            (logical_key, sha, task_id),
        ).fetchone()
        if existing:
            return self.get(existing[0])  # type: ignore[return-value]

        ref = ArtifactRef(
            sha=sha, kind=kind, bytes=len(raw), task_id=task_id, logical_key=logical_key,
            parent_id=parent_id, trust=trust, truncated=truncated, meta=meta or {},
        )
        self._conn.execute(
            "INSERT INTO version (id, logical_key, kind, sha, task_id, parent_id, trust, "
            "truncated, archived, meta, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ref.id, ref.logical_key, ref.kind, ref.sha, ref.task_id, ref.parent_id,
             ref.trust, int(ref.truncated), 0, json.dumps(ref.meta), ref.ts),
        )
        self._conn.commit()
        return ref

    # -- read ------------------------------------------------ #
    def _row(self, r: tuple) -> ArtifactRef:
        return ArtifactRef(
            id=r[0], logical_key=r[1], kind=r[2], sha=r[3], task_id=r[4], parent_id=r[5],
            trust=r[6], truncated=bool(r[7]), archived=bool(r[8]),
            meta=json.loads(r[9] or "{}"), ts=r[10],
            bytes=self._blob_bytes(r[3]),
        )

    _COLS = "id, logical_key, kind, sha, task_id, parent_id, trust, truncated, archived, meta, ts"

    def get(self, artifact_id: str) -> ArtifactRef | None:
        r = self._conn.execute(
            f"SELECT {self._COLS} FROM version WHERE id=?", (artifact_id,)
        ).fetchone()
        return self._row(r) if r else None

    def content(self, artifact_id: str) -> bytes | None:
        r = self._conn.execute(
            "SELECT b.data FROM version v JOIN blob b ON b.sha=v.sha WHERE v.id=?",
            (artifact_id,),
        ).fetchone()
        return bytes(r[0]) if r else None

    def text(self, artifact_id: str) -> str:
        data = self.content(artifact_id)
        return data.decode("utf-8", errors="replace") if data else ""

    def latest_for(self, logical_key: str) -> ArtifactRef | None:
        r = self._conn.execute(
            f"SELECT {self._COLS} FROM version WHERE logical_key=? ORDER BY seq DESC LIMIT 1",
            (logical_key,),
        ).fetchone()
        return self._row(r) if r else None

    def history(self, logical_key: str) -> list[ArtifactRef]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM version WHERE logical_key=? ORDER BY seq DESC",
            (logical_key,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def chain(self, artifact_id: str) -> list[ArtifactRef]:
        out: list[ArtifactRef] = []
        seen: set[str] = set()
        cur = self.get(artifact_id)
        while cur and cur.id not in seen:
            seen.add(cur.id)
            out.append(cur)
            cur = self.get(cur.parent_id) if cur.parent_id else None
        return out

    def diff_versions(self, a_id: str, b_id: str) -> str:
        a, b = self.get(a_id), self.get(b_id)
        if not a or not b or a.kind != b.kind or a.kind not in _TEXT_KINDS:
            return ""
        left = self.text(a_id).splitlines(keepends=True)
        right = self.text(b_id).splitlines(keepends=True)
        return "".join(difflib.unified_diff(left, right, a_id, b_id, n=3))

    def active(self) -> list[ArtifactRef]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM version WHERE archived=0 ORDER BY seq"
        ).fetchall()
        return [self._row(r) for r in rows]

    def all(self, *, include_archived: bool = True) -> list[ArtifactRef]:
        q = f"SELECT {self._COLS} FROM version"
        if not include_archived:
            q += " WHERE archived=0"
        q += " ORDER BY seq"
        return [self._row(r) for r in self._conn.execute(q).fetchall()]

    # -- retention (§11.3 — mark, never delete) ------------- #
    def archive_before(self, ts: float) -> int:
        cur = self._conn.execute("UPDATE version SET archived=1 WHERE ts < ? AND archived=0", (ts,))
        self._conn.commit()
        return cur.rowcount

    def _blob_bytes(self, sha: str) -> int:
        r = self._conn.execute("SELECT bytes FROM blob WHERE sha=?", (sha,)).fetchone()
        return int(r[0]) if r else 0

    def close(self) -> None:
        self._conn.close()
