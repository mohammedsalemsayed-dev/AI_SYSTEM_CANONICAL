"""Acceptance (Unit): content-addressed artifact store + version chain
(MILESTONE_P_PLAN.md §6)."""

from __future__ import annotations

import time

from app.services.artifacts.store import MAX_ARTIFACT_BYTES, ArtifactStore


def test_dedup_blob_but_distinct_versions() -> None:
    s = ArtifactStore()
    a = s.put("diff", "same content\n", task_id="t1", logical_key="k")
    b = s.put("diff", "same content\n", task_id="t2", logical_key="k")
    assert a.sha == b.sha and a.id != b.id
    assert s._conn.execute("SELECT COUNT(*) FROM blob").fetchone()[0] == 1
    assert s._conn.execute("SELECT COUNT(*) FROM version").fetchone()[0] == 2
    s.close()


def test_auto_parent_link_and_history_order() -> None:
    s = ArtifactStore()
    v1 = s.put("diff", "v1\n", task_id="t", logical_key="k")
    v2 = s.put("diff", "v2\n", task_id="t", logical_key="k")
    v3 = s.put("diff", "v3\n", task_id="t", logical_key="k")
    assert v1.parent_id is None and v2.parent_id == v1.id and v3.parent_id == v2.id
    hist = s.history("k")
    assert [h.id for h in hist] == [v3.id, v2.id, v1.id]
    assert [c.id for c in s.chain(v3.id)] == [v3.id, v2.id, v1.id]
    s.close()


def test_chain_is_cycle_safe() -> None:
    s = ArtifactStore()
    a = s.put("diff", "a\n", logical_key="k")
    b = s.put("diff", "b\n", logical_key="k")
    # forge a cycle: point a's parent at b
    s._conn.execute("UPDATE version SET parent_id=? WHERE id=?", (b.id, a.id))
    s._conn.commit()
    chain = s.chain(a.id)
    assert len(chain) == 2 and chain[0].id == a.id  # terminates
    s.close()


def test_diff_versions_text_and_binary() -> None:
    s = ArtifactStore()
    a = s.put("document", "line one\nline two\n", logical_key="d")
    b = s.put("document", "line one\nline two changed\nline three\n", logical_key="d")
    d = s.diff_versions(a.id, b.id)
    assert "-line two" in d and "+line two changed" in d and "+line three" in d
    fs1 = s.put("file_snapshot", b"\x00\x01", logical_key="f")
    fs2 = s.put("file_snapshot", b"\x00\x02", logical_key="f")
    assert s.diff_versions(fs1.id, fs2.id) == ""          # non-text kind
    assert s.diff_versions(a.id, "missing") == ""
    s.close()


def test_archive_marks_never_deletes() -> None:
    s = ArtifactStore()
    s.put("diff", "old\n", logical_key="k")
    time.sleep(0.01)
    cutoff = time.time()
    time.sleep(0.01)
    s.put("diff", "new\n", logical_key="k")
    n = s.archive_before(cutoff)
    assert n == 1
    assert len(s.all(include_archived=True)) == 2
    assert len(s.active()) == 1
    s.close()


def test_truncation_flag() -> None:
    s = ArtifactStore()
    big = "x" * (MAX_ARTIFACT_BYTES + 100)
    ref = s.put("document", big, logical_key="k")
    assert ref.truncated and ref.bytes == MAX_ARTIFACT_BYTES
    assert len(s.text(ref.id)) == MAX_ARTIFACT_BYTES
    s.close()


def test_unknown_id_returns_none() -> None:
    s = ArtifactStore()
    assert s.get("nope") is None and s.content("nope") is None and s.text("nope") == ""
    s.close()


def test_idempotent_on_logical_key_sha_task() -> None:
    s = ArtifactStore()
    a = s.put("diff", "c\n", task_id="t", logical_key="k")
    again = s.put("diff", "c\n", task_id="t", logical_key="k")
    assert again.id == a.id
    assert s._conn.execute("SELECT COUNT(*) FROM version").fetchone()[0] == 1
    s.close()
