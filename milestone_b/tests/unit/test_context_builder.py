"""Acceptance (Unit): the context builder assembles decisions / constraints /
open questions / retrieval hits (MILESTONE_F_PLAN.md §6)."""

from __future__ import annotations

from app.schemas.contracts import MemoryRecord
from app.services.memory.context import build_context
from app.services.memory.store import MemoryStore


def test_none_store_returns_empty() -> None:
    assert build_context(None, "anything") == ""


def test_empty_store_returns_empty() -> None:
    assert build_context(MemoryStore(), "anything") == ""


def test_context_lists_decisions_and_constraints() -> None:
    s = MemoryStore()
    s.put(MemoryRecord(tier="project", kind="decision", content="use pydantic v2 everywhere"))
    s.put(MemoryRecord(tier="project", kind="constraint", content="no network in the sandbox"))
    s.put(MemoryRecord(tier="project", kind="open_question", content="which db for prod?"))
    ctx = build_context(s, "add a schema")
    assert "ACTIVE DECISIONS" in ctx and "pydantic v2" in ctx
    assert "CONSTRAINTS" in ctx and "no network" in ctx
    assert "OPEN QUESTIONS" in ctx and "which db" in ctx
    s.close()


def test_context_shows_artifact_index_section() -> None:
    s = MemoryStore()
    s.put(MemoryRecord(tier="project", kind="artifact_index",
                       content="fix the parser -> touched parser.py"))
    ctx = build_context(s, "the parser is broken again")
    assert "ARTIFACT INDEX" in ctx and "parser.py" in ctx
    s.close()


def test_context_adds_relevant_retrieval_hits() -> None:
    s = MemoryStore()
    s.put(MemoryRecord(tier="experience", kind="note",
                       content="a working strategy for parser off-by-one bugs"))
    ctx = build_context(s, "the parser has an off-by-one again")
    assert "POSSIBLY RELEVANT" in ctx and "off-by-one" in ctx
    s.close()


def test_context_does_not_duplicate_a_shown_decision() -> None:
    s = MemoryStore()
    s.put(MemoryRecord(tier="project", kind="decision",
                       content="always validate the parser input"))
    ctx = build_context(s, "parser validation")
    # the decision appears once (under ACTIVE DECISIONS), not again under POSSIBLY RELEVANT
    assert ctx.count("always validate the parser input") == 1
    s.close()
