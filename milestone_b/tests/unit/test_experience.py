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


# --- days 9-10: offline eval + validate/promote/sweep ----------- #
def _shadow(st: ExperienceStore, exp_id: str, *, n=5, ok=5) -> None:
    for i in range(n):
        st.add_shadow_result(exp_id, verified=(i < ok), cost_ratio=1.0, week=i + 1)


def test_try_validate_respects_shadow_gate() -> None:
    st = ExperienceStore()
    e = st.capture(signature="code_edit_local|tags=off-by-one|tools=builder", strategy="guard",
                   actions=[], evidence_refs=[], success_score=1.0, verify_tier="T0")
    _, ok, _ = st.try_validate(e.id)
    assert not ok  # no shadow tasks yet
    _shadow(st, e.id, n=5, ok=3)  # 60% < 80%
    _, ok, why = st.try_validate(e.id)
    assert not ok and "success" in why
    _shadow(st, e.id, n=5, ok=5)  # now 8/10 = 80% across weeks 1..5
    e2, ok, _ = st.try_validate(e.id)
    assert ok and e2.validation_state == "VALIDATED"
    st.close()


def test_try_promote_needs_human_for_security_strategy() -> None:
    st = ExperienceStore()
    e = st.capture(signature="code_edit_local|tags=auth|tools=builder",
                   strategy="tighten the auth check", actions=["auth.py"],
                   evidence_refs=[], success_score=1.0, verify_tier="T0")
    _shadow(st, e.id, n=12, ok=12)
    st.try_validate(e.id)
    _, decision = st.try_promote(e.id, human_approved=False)
    assert decision.needs_human and not decision.ok
    e2, decision2 = st.try_promote(e.id, human_approved=True)
    assert decision2.ok and e2.validation_state == "MONITORED"  # auto after PROMOTED
    st.close()


def test_try_promote_plain_strategy_auto_monitors() -> None:
    st = ExperienceStore()
    e = st.capture(signature="code_edit_local|tags=off-by-one|tools=builder", strategy="fix range",
                   actions=["p.py"], evidence_refs=[], success_score=1.0, verify_tier="T0")
    _shadow(st, e.id, n=12, ok=12)
    st.try_validate(e.id)
    e2, decision = st.try_promote(e.id)
    assert decision.ok and e2.validation_state == "MONITORED"
    st.close()


def test_sweep_stale_moves_low_trailing_success() -> None:
    st = ExperienceStore()
    e = st.capture(signature="s", strategy="x", actions=[], evidence_refs=[],
                   success_score=1.0, verify_tier="T0")
    st.advance(e.id, "VALIDATED", note="")
    st.advance(e.id, "PROMOTED", note="")
    st.advance(e.id, "MONITORED", note="")
    cur = st.get(e.id)
    cur.monitoring_metrics = {"trailing_n": 20, "trailing_success": 0.5}
    st._update(cur)
    moved = st.sweep_stale()
    assert [m.id for m in moved] == [e.id]
    assert st.get(e.id).validation_state == "STALE"
    st.close()
