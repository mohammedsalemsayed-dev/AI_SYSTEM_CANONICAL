"""Acceptance (Unit): Critic report parsing incl. fail-open on bad output
(MILESTONE_E_PLAN.md §7)."""

from __future__ import annotations

import json

from app.llm.fake import ScriptedLLM
from app.schemas.contracts import TaskContract
from app.services.agents.critic import Critic

_C = TaskContract(
    task_id="t", original_request="r", objective="make it work",
    success_criteria=["x"], required_evidence=["T0: pytest a.py passes"],
)


def _critic(reply: str) -> Critic:
    return Critic(ScriptedLLM([reply]))


def test_parses_accept() -> None:
    r, run = _critic(json.dumps({"verdict": "accept", "summary": "fine", "findings": []})).review(
        "t", _C, "diff", "test text"
    )
    assert r.verdict == "accept" and run.role == "critic"


def test_parses_reject_with_findings() -> None:
    reply = json.dumps({
        "verdict": "reject",
        "summary": "message mismatch",
        "findings": [
            {"severity": "blocking", "claim": "raises the wrong message"},
            {"severity": "minor", "claim": "docstring not updated"},
        ],
    })
    r, _ = _critic(reply).review("t", _C, "diff", "test")
    assert r.verdict == "reject"
    assert len(r.findings) == 2
    assert r.findings[0].severity == "blocking"


def test_unknown_verdict_becomes_accept() -> None:
    r, _ = _critic(json.dumps({"verdict": "lgtm", "findings": []})).review("t", _C, "d", "t")
    assert r.verdict == "accept"


def test_malformed_output_fails_open_to_accept() -> None:
    r, run = _critic("not json at all").review("t", _C, "d", "t")
    assert r.verdict == "accept"
    assert run.failure_mode == "critic_error"
    assert "critic unavailable" in r.summary


def test_empty_claims_are_dropped() -> None:
    reply = json.dumps({"verdict": "revise", "findings": [{"claim": ""}, {"claim": "real one"}]})
    r, _ = _critic(reply).review("t", _C, "d", "t")
    assert [f.claim for f in r.findings] == ["real one"]
