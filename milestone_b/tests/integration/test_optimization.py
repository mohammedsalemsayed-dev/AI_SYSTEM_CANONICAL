"""Acceptance (Integration): a real EvalReport gates experience promotion; a
guardrail regression blocks it; a freshly-promoted experience whose canary
cohort underperforms is auto-quarantined (MILESTONE_I_PLAN.md §6)."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.schemas.contracts import SuiteResult
from app.services.eval.offline_eval import OfflineEval
from app.services.eval.regression import RegressionBaseline, check_regression
from app.services.experience.store import ExperienceStore
from app.services.memory.store import MemoryStore
from tests.conftest import FIXED_CALC
from tests.integration.conftest import (
    build_orchestrator,
    interpreter_reply,
    planner_reply,
)


def _validated_exp(store: ExperienceStore) -> str:
    exp = store.capture(signature="code_edit_local|tags=off-by-one|tools=builder",
                        strategy="add a boundary guard", actions=["m.py"],
                        evidence_refs=["v1"], success_score=1.0, verify_tier="T0")
    store.advance(exp.id, "VALIDATED", note="test")
    return exp.id


def _eval(guardrail: SuiteResult):
    base = SuiteResult(n=12, passed=12, failures=[])
    return OfflineEval(
        run_with=lambda t: True,
        run_without=lambda t: t.endswith("0"),
        certify_guardrail=lambda s: check_regression(s, base),
        run_guardrail=lambda: guardrail,
    )


def test_real_eval_report_promotes_when_guardrail_holds() -> None:
    st = ExperienceStore()
    eid = _validated_exp(st)
    report = _eval(SuiteResult(n=12, passed=12, failures=[])).evaluate(eid, [f"t{i}" for i in range(10)])
    exp, decision = st.try_promote(eid, report=report)
    assert decision.decision == "promote"
    assert exp.validation_state == "MONITORED"
    assert exp.monitoring_metrics["heldout_n"] == 10
    st.close()


def test_guardrail_regression_blocks_promotion() -> None:
    st = ExperienceStore()
    eid = _validated_exp(st)
    report = _eval(SuiteResult(n=12, passed=11, failures=["pagination"])).evaluate(
        eid, [f"t{i}" for i in range(10)]
    )
    exp, decision = st.try_promote(eid, report=report)
    assert decision.decision == "hold" and "guardrail" in decision.why
    assert exp.validation_state == "VALIDATED"  # did not advance
    st.close()


def test_regression_baseline_persists_in_system_memory() -> None:
    mem = MemoryStore()
    RegressionBaseline(mem).set_baseline(SuiteResult(n=12, passed=12, failures=[]))
    # a fresh handle over the same store certifies against it
    got = RegressionBaseline(mem).certify(SuiteResult(n=12, passed=12, failures=[]))
    assert got.passed and got.baseline_rate == 1.0
    mem.close()


def test_experience_canary_rolls_back_a_bad_promotion(sample_repo: str) -> None:
    log = EventLog()
    exp_store = ExperienceStore()
    # a PROMOTED experience whose signature matches the sample_repo task
    exp = exp_store.capture(signature="code_edit_local|tags=|tools=builder",
                            strategy="the risky strategy", actions=["calc.py"],
                            evidence_refs=["v1"], success_score=0.9, verify_tier="T0")
    exp_store.advance(exp.id, "VALIDATED", note="t")
    exp_store.advance(exp.id, "PROMOTED", note="t")

    # builder writes a wrong body every run -> every task fails T0
    def bad(ws: str) -> None:
        (__import__("pathlib").Path(ws) / "calc.py").write_text(
            "def add(a, b):\n    return a - b\n", newline="\n"
        )

    runs = 4
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()] * runs,
        builder_edits=bad,
    )
    orch.experience = exp_store
    orch.canary_enabled = True
    orch.canary_fraction = 1.0
    orch.canary_min_samples = 3

    fails = 0
    for _ in range(runs):
        r = orch.run("fix the add function", sample_repo)
        if r.state != "COMPLETED":
            fails += 1

    assert fails == runs
    canary_events = [e.payload for e in log.all() if e.kind == EventKind.CANARY]
    assert any(e["verdict"] == "ROLLBACK" for e in canary_events)
    assert exp_store.get(exp.id).validation_state == "QUARANTINED"
    exp_store.close()
    log.close()
