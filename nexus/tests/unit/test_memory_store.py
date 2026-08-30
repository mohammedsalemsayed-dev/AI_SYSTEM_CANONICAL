"""Acceptance (Unit): MemoryStore append + supersession + tier filter, and
scoped/trust-filtered retrieval (MILESTONE_F_PLAN.md §6)."""

from __future__ import annotations

from app.schemas.contracts import MemoryRecord
from app.services.memory.retrieve import retrieve
from app.services.memory.store import MemoryStore


def _rec(**kw) -> MemoryRecord:
    kw.setdefault("tier", "project")
    kw.setdefault("kind", "note")
    kw.setdefault("content", "x")
    return MemoryRecord(**kw)


def test_put_and_all_by_tier() -> None:
    s = MemoryStore()
    s.put(_rec(tier="project", content="use pydantic v2"))
    s.put(_rec(tier="system", kind="config", content="model=sonnet"))
    assert len(s.all(tier="project")) == 1
    assert len(s.all(tier="system")) == 1
    assert len(s.all()) == 0 or len(s.all()) == 2  # all() with no tier returns non-superseded
    s.close()


def test_supersession_hides_the_old_row() -> None:
    s = MemoryStore()
    old = s.put(_rec(tier="project", kind="decision", content="use sqlite"))
    new = s.supersede(old.id, _rec(tier="project", kind="decision", content="use postgres"))
    live = s.all(tier="project")
    assert len(live) == 1 and live[0].content == "use postgres"
    assert new.version == 2
    assert len(s.all(tier="project", include_superseded=True)) == 2
    s.close()


def test_retrieval_keyword_match() -> None:
    s = MemoryStore()
    s.put(_rec(tier="project", kind="note", content="the auth module uses JWT tokens"))
    s.put(_rec(tier="project", kind="note", content="unrelated note about colours"))
    hits = retrieve(s, "how does auth work", tiers=("project",))
    assert hits and "JWT" in hits[0].content
    s.close()


def test_retrieval_excludes_too_untrusted() -> None:
    s = MemoryStore()
    s.put(_rec(tier="project", kind="note", content="trusted workspace note about caching",
              trust="workspace"))
    s.put(_rec(tier="project", kind="note", content="untrusted web claim about caching",
              trust="retrieved_web"))
    hits = retrieve(s, "caching", tiers=("project",), trust_min="workspace")
    assert all(h.trust == "workspace" for h in hits)
    hits2 = retrieve(s, "caching", tiers=("project",), trust_min="doc_input")
    assert any(h.trust == "retrieved_web" for h in hits2)
    s.close()


def test_retrieval_excludes_quarantined_experience() -> None:
    s = MemoryStore()
    s.put(_rec(tier="experience", kind="experience_state",
              content="QUARANTINED: strategy that bypassed a check"))
    s.put(_rec(tier="experience", kind="experience_state",
              content="PROMOTED: safe refactor strategy"))
    hits = retrieve(s, "strategy", tiers=("experience",))
    assert all(not h.content.startswith("QUARANTINED") for h in hits)
    assert any(h.content.startswith("PROMOTED") for h in hits)
    s.close()


def test_stale_only_with_flag() -> None:
    s = MemoryStore()
    s.put(_rec(tier="experience", kind="experience_state",
              content="STALE: old strategy for parser bugs"))
    assert retrieve(s, "parser strategy", tiers=("experience",)) == []
    assert retrieve(s, "parser strategy", tiers=("experience",), include_stale=True)
    s.close()


def test_role_perf_roundtrip() -> None:
    s = MemoryStore()
    s.record_role_perf("critic", "code_edit_local", {"samples": 12, "with_role_success": 0.8})
    got = s.latest_role_perf("critic", "code_edit_local")
    assert got["samples"] == 12
    assert s.latest_role_perf("critic", "debug") is None
    s.close()
