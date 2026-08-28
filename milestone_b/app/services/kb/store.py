"""KnowledgeBase (MILESTONE_L_PLAN.md §2, §11.3).

SQLite documents + chunks. The retrieval index is derived — `rebuild_index()`
reconstructs it from the chunk table and it may be dropped freely. Ingest scans
each document for instruction-like content (reuse `research/injection.py`).
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from app.services.kb.chunk import chunk as _chunk
from app.services.kb.lexical import LexicalIndex
from app.services.research.injection import scan as _scan

MAX_FILE_BYTES = 2 * 1024 * 1024
_TEXT_SUFFIXES = {
    ".md", ".markdown", ".rst", ".txt", ".text", ".py", ".pyi", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".csv", ".tsv", ".js", ".ts", ".go", ".rs", ".java", ".c",
    ".h", ".cpp", ".sh", ".html", ".xml", ".pdf",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS document (
    id TEXT PRIMARY KEY, uri TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
    sha TEXT NOT NULL, bytes INTEGER NOT NULL, ts REAL NOT NULL, flags TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chunk (
    id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, ord INTEGER NOT NULL,
    heading TEXT NOT NULL DEFAULT '', text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunk_doc ON chunk (doc_id);
"""


def _is_binary(data: bytes) -> bool:
    head = data[:8192]
    if not head:
        return False
    nontext = sum(1 for b in head if b < 9 or (13 < b < 32))
    return nontext / len(head) > 0.10


class KnowledgeBase:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._index: LexicalIndex | None = None

    # -- ingest ------------------------------------------------ #
    def ingest_text(self, text: str, *, uri: str, title: str = "") -> str:
        sha = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        existing = self._conn.execute(
            "SELECT id FROM document WHERE uri=? AND sha=?", (uri, sha)
        ).fetchone()
        if existing:
            return existing[0]
        # a changed doc at the same uri supersedes the old rows
        self._conn.execute("DELETE FROM chunk WHERE doc_id IN "
                           "(SELECT id FROM document WHERE uri=?)", (uri,))
        self._conn.execute("DELETE FROM document WHERE uri=?", (uri,))

        doc_id = f"doc_{sha[:12]}"
        flags = ",".join(_scan(text))
        self._conn.execute(
            "INSERT INTO document (id, uri, title, sha, bytes, ts, flags) VALUES (?,?,?,?,?,?,?)",
            (doc_id, uri, title or Path(uri).name, sha, len(text.encode("utf-8", "replace")),
             time.time(), flags),
        )
        for ordn, (heading, body) in enumerate(_chunk(text)):
            self._conn.execute(
                "INSERT INTO chunk (id, doc_id, ord, heading, text) VALUES (?,?,?,?,?)",
                (f"{doc_id}:{ordn}", doc_id, ordn, heading, body),
            )
        self._conn.commit()
        self._index = None
        return doc_id

    def ingest_file(self, path: str | Path) -> str | None:
        p = Path(path)
        if p.suffix.lower() not in _TEXT_SUFFIXES or not p.is_file():
            return None
        if p.stat().st_size > MAX_FILE_BYTES:
            return None
        raw = p.read_bytes()
        if _is_binary(raw):
            return None
        text = raw.decode("utf-8", errors="replace")
        return self.ingest_text(text, uri=str(p), title=p.name)

    def ingest_dir(self, root: str | Path) -> list[str]:
        out = []
        for f in sorted(Path(root).rglob("*")):
            if f.is_file():
                did = self.ingest_file(f)
                if did:
                    out.append(did)
        return out

    def remove(self, doc_id: str) -> None:
        self._conn.execute("DELETE FROM chunk WHERE doc_id=?", (doc_id,))
        self._conn.execute("DELETE FROM document WHERE id=?", (doc_id,))
        self._conn.commit()
        self._index = None

    # -- read ------------------------------------------------ #
    def documents(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, uri, title, bytes, ts, flags FROM document ORDER BY ts"
        ).fetchall()
        return [
            {"id": r[0], "uri": r[1], "title": r[2], "bytes": r[3], "ts": r[4],
             "flags": [f for f in r[5].split(",") if f]}
            for r in rows
        ]

    def chunks(self, doc_id: str | None = None) -> list[tuple[str, str]]:
        if doc_id:
            rows = self._conn.execute(
                "SELECT id, text FROM chunk WHERE doc_id=? ORDER BY ord", (doc_id,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT id, text FROM chunk ORDER BY doc_id, ord").fetchall()
        return [(r[0], r[1]) for r in rows]

    def chunk_meta(self, chunk_id: str) -> dict | None:
        r = self._conn.execute(
            "SELECT c.id, c.doc_id, c.heading, c.text, d.uri, d.title, d.flags "
            "FROM chunk c JOIN document d ON d.id=c.doc_id WHERE c.id=?", (chunk_id,)
        ).fetchone()
        if not r:
            return None
        return {"chunk_id": r[0], "doc_id": r[1], "heading": r[2], "text": r[3],
                "uri": r[4], "title": r[5], "flags": [f for f in r[6].split(",") if f]}

    def all_document_flags(self) -> list[str]:
        out: list[str] = []
        for d in self.documents():
            out += [f"{f}@{d['title']}" for f in d["flags"]]
        return out

    def index_chunks(self) -> list[tuple[str, str]]:
        """Chunks with their heading folded into the indexed text — a heading is
        strong retrieval signal."""
        rows = self._conn.execute(
            "SELECT id, heading, text FROM chunk ORDER BY doc_id, ord"
        ).fetchall()
        return [(r[0], (r[1] + "\n" + r[2]) if r[1] else r[2]) for r in rows]

    # -- index (derived) ---------------------------------- #
    def rebuild_index(self) -> LexicalIndex:
        self._index = LexicalIndex.build(self.index_chunks())
        return self._index

    def index(self) -> LexicalIndex:
        if self._index is None:
            self.rebuild_index()
        assert self._index is not None
        return self._index

    def is_empty(self) -> bool:
        return self._conn.execute("SELECT COUNT(*) FROM chunk").fetchone()[0] == 0

    def close(self) -> None:
        self._conn.close()
