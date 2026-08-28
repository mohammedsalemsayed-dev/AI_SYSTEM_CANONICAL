"""Acceptance (Unit): T2 ensemble verifier + the disagreement protocol
(MILESTONE_E_PLAN.md §7)."""

from __future__ import annotations

import json

from app.llm.fake import ScriptedLLM
from app.schemas.contracts import TaskContract, VerificationRecord
from app.services.agents.disagreement import resolve
from app.services.verify.verifier_t2 import VerifierT2

_C = TaskContract(
    task_id="t", original_request="r", objective="o",
    success_criteria=["add returns a + b"],
    required_evidence=["T0: pytest a.py passes"],
)


def _pass() -> str:
    return json.dumps({"criteria": [{"criterion": "c", "verdict": "pass", "note": ""}], "overall": "pass"})


def _fail() -> str:
    return json.dumps({"criteria": [{"criterion": "c", "verdict": "fail", "note": "x"}], "overall": "fail"})


def test_unanimous_pass() -> None:
    v = VerifierT2(ScriptedLLM([_pass(), _pass()]), contexts=2)
    rec, run = v.verify(task_id="t", contract=_C, diff="d")
    assert rec.overall == "pass" and rec.tier == "T2"
    assert not VerifierT2.is_split(rec)
    assert run.role == "verifier_t2"


def test_unanimous_fail() -> None:
    v = VerifierT2(ScriptedLLM([_fail(), _fail()]), contexts=2)
    rec, _ = v.verify(task_id="t", contract=_C, diff="d")
    assert rec.overall == "fail" and not VerifierT2.is_split(rec)


def test_split_contexts_flagged() -> None:
    v = VerifierT2(ScriptedLLM([_pass(), _fail()]), contexts=2)
    rec, _ = v.verify(task_id="t", contract=_C, diff="d")
    assert rec.overall == "fail"  # conservative on a split
    assert VerifierT2.is_split(rec)


def test_broken_context_abstains_as_fail() -> None:
    v = VerifierT2(ScriptedLLM([_pass(), "garbage"]), contexts=2)
    rec, _ = v.verify(task_id="t", contract=_C, diff="d")
    assert rec.overall == "fail"


# --- disagreement protocol ---------------------------------------- #
def _rec(tier: str, overall: str) -> VerificationRecord:
    return VerificationRecord(task_id="t", tier=tier, overall=overall)


def test_resolve_when_t0_and_t2_agree() -> None:
    out = resolve(_C, _rec("T0", "pass"), _rec("T2", "pass"))
    assert out.resolution == "t0_authoritative"


def test_resolve_escalates_on_risky_disagreement() -> None:
    risky = _C.model_copy(update={"risk_level": "high"})
    out = resolve(risky, _rec("T0", "pass"), _rec("T2", "fail"))
    assert out.resolution == "escalate"
    assert "human should review" in out.detail


def test_resolve_low_risk_disagreement_t0_stands() -> None:
    out = resolve(_C, _rec("T0", "pass"), _rec("T2", "fail"))  # risk_level low
    assert out.resolution == "t0_authoritative"
    assert "T2 concern noted" in out.detail


def test_resolve_t2_pass_t0_fail_never_escalates() -> None:
    risky = _C.model_copy(update={"risk_level": "high"})
    out = resolve(risky, _rec("T0", "fail"), _rec("T2", "pass"))
    assert out.resolution == "t0_authoritative"  # T0 fail stands; T2 optimism ignored
