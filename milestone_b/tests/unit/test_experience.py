"""Acceptance (Unit): situation signature + experience lifecycle gates + store
(MILESTONE_F_PLAN.md §6, §7)."""

from __future__ import annotations

from app.schemas.contracts import ExperienceRecord, TaskContract
from app.services.experience.lifecycle import (
    can_transition,
    gate_candidate_to_validated,
    gate_observed_to_candidate,
    gate_validated_to_promoted,
    should_go_stale,
    should_quarantine,
)
from app.services.experience.signature import signatures_match, situation_signature
from app.services.experience.store import ExperienceStore


def _c(objective="fix the off-by-one in pagination", task_class="code_edit_local") -> TaskContract:
    return TaskContract(
        task_id="t", original_request=objective, objective=objective,
        task_class=task_class, success_criteria=["x"],
        required_evidence=["T0: pytest a.py passes"],
    )


# --- signature ---------------------------------------------------- #
def test_signature_stable_for_same_contract() -> None:
    a = situation_signature(_c(), ["builder"])
    b = situation_signature(_c(), ["builder"])
    assert a == b


def test_signature_differs_by_task_class() -> None:
    a = situation_signature(_c(task_class="code_edit_local"), ["builder"])
    b = situation_signature(_c(task_class="debug"), ["builder"])
    assert a != b


def test_signatures_match_on_class_and_tag_overlap() -> None:
    a = situation_signature(_c("fix the off-by-one boundary"), ["builder"])
    b = situation_signature(_c("another off-by-one boundary bug"), ["builder"])
    assert signatures_match(a, b)
    c = situation_signature(_c("a caching concurrency issue"), ["builder"])
    assert not signatures_match(a, c)


# --- gates ------------------------------------------------------ #
def test_observed_to_candidate_needs_new_and_verified() -> None:
    ok, _ = gate_observed_to_candidate(verify_tier="T0", is_new_signature_strategy=True)
    assert ok
    ok2, _ = gate_observed_to_candidate(verify_tier="T0", is_new_signature_strategy=False)
    assert not ok2


def test_candidate_to_validated_gate() -> None:
    exp = ExperienceRecord(signature="s", strategy="x")
    assert not gate_candidate_to_validated(exp)[0]  # empty log
    exp.shadow_replay_log = [
        {"verified": True, "cost_ratio": 1.0, "week": w} for w in (1, 2, 3, 4, 5)
    ]
    assert gate_candidate_to_validated(exp)[0]
    exp.shadow_replay_log[0]["verified"] = False
    exp.shadow_replay_log.append({"verified": False, "cost_ratio": 1.0, "week": 6})
    ok, why = gate_candidate_to_validated(exp)
    assert not ok and "success" in why


def test_validated_to_promoted_gate() -> None:
    exp = ExperienceRecord(signature="s", strategy="x", guardrail_result=1.0,
                           monitoring_metrics={"heldout_n": 10})
    assert gate_validated_to_promoted(exp)[0]
    exp.guardrail_result = 5.0
    assert not gate_validated_to_promoted(exp)[0]


def test_stale_and_quarantine_conditions() -> None:
    exp = ExperienceRecord(signature="s", strategy="x",
                           monitoring_metrics={"trailing_n": 20, "trailing_success": 0.5})
    assert should_go_stale(exp)[0]
    exp.monitoring_metrics = {"trailing_n": 5, "trailing_success": 0.2}
    assert should_quarantine(exp)[0]
    assert should_quarantine(ExperienceRecord(signature="s", strategy="x"), catastrophic=True)[0]


def test_transition_map() -> None:
    assert can_transition("OBSERVED", "CANDIDATE")
    assert can_transition("PROMOTED", "QUARANTINED")
    assert not can_transition("STALE", "PROMOTED")


# --- store ------------------------------------------------------ #
def test_capture_auto_advances_new_to_candidate() -> None:
    st = ExperienceStore()
    exp = st.capture(signature="sig1", strategy="add a guard", actions=["a.py"],
                     evidence_refs=["ver1"], success_score=1.0, verify_tier="T0")
    assert exp.validation_state == "CANDIDATE"
    # a second capture of the same (signature, strategy) stays OBSERVED
    dup = st.capture(signature="sig1", strategy="add a guard", actions=["a.py"],
                     evidence_refs=["ver2"], success_score=1.0, verify_tier="T0")
    assert dup.validation_state == "OBSERVED"
    st.close()


def test_retrieve_matches_and_skips_quarantined() -> None:
    st = ExperienceStore()
    e1 = st.capture(signature="code_edit_local|tags=boundary|tools=builder", strategy="s1",
                    actions=[], evidence_refs=[], success_score=1.0, verify_tier="T0")
    st.advance(e1.id, "VALIDATED", note="test")
    e2 = st.capture(signature="code_edit_local|tags=boundary|tools=builder", strategy="s2",
                    actions=[], evidence_refs=[], success_score=1.0, verify_tier="T0")
    st.advance(e2.id, "VALIDATED", note="test")
    st.advance(e2.id, "QUARANTINED", note="bad")
    hits = st.retrieve("code_edit_local|tags=boundary|tools=builder", states=("VALIDATED",))
    assert [h.strategy for h in hits] == ["s1"]
    st.close()


def test_record_use_quarantines_on_bad_streak() -> None:
    st = ExperienceStore()
    e = st.capture(signature="s", strategy="x", actions=[], evidence_refs=[],
                   success_score=1.0, verify_tier="T0")
    st.advance(e.id, "VALIDATED", note="")
    st.advance(e.id, "PROMOTED", note="")
    for _ in range(5):
        e = st.record_use(e.id, verified=False)
    assert e.validation_state == "QUARANTINED"
    st.close()
