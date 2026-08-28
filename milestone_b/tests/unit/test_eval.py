"""Acceptance (Unit): guardrail suite, regression gate, offline eval, canary,
derived metrics (MILESTONE_I_PLAN.md §6)."""

from __future__ import annotations

from app.events.log import EventKind, EventLog
from app.schemas.contracts import SuiteResult
from app.services.eval.canary import CanaryController
from app.services.eval.guardrail import GuardrailSuite, load_suite
from app.services.eval.metrics import rebuild_metrics
from app.services.eval.offline_eval import OfflineEval
from app.services.eval.regression import (
    MAX_GUARDRAIL_DROP_PP,
    RegressionBaseline,
    check_regression,
)
from app.services.memory.store import MemoryStore


# --- guardrail suite ------------------------------------------- #
def test_suite_loads_and_runs_in_stable_order() -> None:
    s = GuardrailSuite()
    ids = s.ids()
    assert len(ids) >= 12 and ids == load_suite_ids()
    seen: list[str] = []
    r = s.run(lambda t: seen.append(t.id) or True)
    assert seen == ids
    assert r.n == len(ids) and r.passed == len(ids) and r.failures == []


def test_suite_counts_failures_and_treats_crash_as_fail() -> None:
    s = GuardrailSuite()

    def run_one(t):
        if t.id == "parser":
            raise RuntimeError("boom")
        return t.id != "pagination"

    r = s.run(run_one)
    assert set(r.failures) == {"parser", "pagination"}
    assert r.passed == r.n - 2


def load_suite_ids() -> list[str]:
    return [t.id for t in load_suite()]


# --- regression gate ---------------------------------------- #
def test_regression_gate_pass_and_fail_sides() -> None:
    base = SuiteResult(n=12, passed=12, failures=[])
    assert check_regression(SuiteResult(n=12, passed=12, failures=[]), base).passed
    # one newly-failing task -> fail regardless of aggregate
    bad = check_regression(SuiteResult(n=12, passed=11, failures=["pagination"]), base)
    assert not bad.passed and bad.newly_failing == ["pagination"]
    # aggregate drop beyond tolerance with no *new* failure is impossible here,
    # but a smaller baseline shows the drop_pp branch
    base2 = SuiteResult(n=100, passed=100, failures=[f"t{i}" for i in []])
    cand2 = SuiteResult(n=100, passed=97, failures=[f"t{i}" for i in range(3)])
    res2 = check_regression(cand2, base2)
    assert not res2.passed and res2.drop_pp == 3.0 > MAX_GUARDRAIL_DROP_PP


def test_regression_recovered_tasks_reported() -> None:
    base = SuiteResult(n=12, passed=10, failures=["a", "b"])
    cand = SuiteResult(n=12, passed=12, failures=[])
    r = check_regression(cand, base)
    assert r.passed and set(r.recovered) == {"a", "b"}


def test_baseline_store_roundtrip_and_certify_fails_closed() -> None:
    mem = MemoryStore()
    rb = RegressionBaseline(mem)
    assert rb.latest() is None
    assert not rb.certify(SuiteResult(n=12, passed=12, failures=[])).passed  # no baseline
    rb.set_baseline(SuiteResult(n=12, passed=11, failures=["pagination"]))
    got = rb.certify(SuiteResult(n=12, passed=11, failures=["pagination"]))
    assert got.passed
    mem.close()


# --- offline eval ------------------------------------------ #
def _ids(n: int) -> list[str]:
    return [f"t{i}" for i in range(n)]


def test_offline_eval_promotes_on_improvement_and_held_guardrail() -> None:
    ev = OfflineEval(
        run_with=lambda t: True,
        run_without=lambda t: t.endswith(("0", "1")),  # ~20% baseline
        certify_guardrail=lambda s: check_regression(s, SuiteResult(n=12, passed=12, failures=[])),
        run_guardrail=lambda: SuiteResult(n=12, passed=12, failures=[]),
    )
    rep = ev.evaluate("exp_x", _ids(10))
    assert rep.decision == "promote" and rep.delta > 0 and rep.guardrail.passed


def test_offline_eval_holds_when_guardrail_regresses() -> None:
    ev = OfflineEval(
        run_with=lambda t: True,
        run_without=lambda t: False,
        certify_guardrail=lambda s: check_regression(s, SuiteResult(n=12, passed=12, failures=[])),
        run_guardrail=lambda: SuiteResult(n=12, passed=11, failures=["pagination"]),
    )
    rep = ev.evaluate("exp_x", _ids(10))
    assert rep.decision == "hold" and "guardrail" in rep.why


def test_offline_eval_holds_below_min_heldout_and_on_regression() -> None:
    ev = OfflineEval(run_with=lambda t: True, run_without=lambda t: False)
    assert ev.evaluate("x", _ids(9)).decision == "hold"
    ev2 = OfflineEval(run_with=lambda t: False, run_without=lambda t: True)
    assert ev2.evaluate("x", _ids(10)).decision == "hold"


def test_offline_eval_security_change_needs_human() -> None:
    ev = OfflineEval(run_with=lambda t: True, run_without=lambda t: False)
    rep = ev.evaluate("tighten the auth policy check", _ids(10))
    assert rep.decision == "hold" and rep.needs_human
    rep2 = ev.evaluate("tighten the auth policy check", _ids(10), human_approved=True)
    assert rep2.decision == "promote"


# --- canary ---------------------------------------------- #
def test_canary_holds_then_rolls_back_on_drop() -> None:
    c = CanaryController(0.9, fraction=1.0, min_samples=10, max_drop_pp=15, seed=1)
    for _ in range(9):
        assert c.record(False) == "HOLD"
    assert c.record(False) == "ROLLBACK"
    assert c.done


def test_canary_promotes_when_it_holds_the_line() -> None:
    c = CanaryController(0.9, fraction=1.0, min_samples=10, max_drop_pp=15, seed=1)
    v = "HOLD"
    for _ in range(10):
        v = c.record(True)
    assert v == "PROMOTE" and c.done


def test_canary_sample_is_deterministic_fraction() -> None:
    c = CanaryController(0.9, fraction=0.5, seed=7)
    keys = [f"task-{i}" for i in range(200)]
    members = [k for k in keys if c.sample(k)]
    assert 60 < len(members) < 140  # ~50%
    # stable for the same key
    assert all(c.sample(k) == c.sample(k) for k in keys)


# --- metrics -------------------------------------------- #
def test_rebuild_metrics_folds_the_log() -> None:
    log = EventLog()
    # task 1: code_edit_local, completed at T0, no rework
    log.append("task1", EventKind.CONTRACT, {"task_class": "code_edit_local"})
    log.append("task1", EventKind.PLAN, {"steps": []})
    log.append("task1", EventKind.VERIFICATION, {"tier": "T0"})
    log.append("task1", EventKind.RESULT, {"state": "COMPLETED", "verified": True})
    # task 2: debug, failed, with an escalation + a hard budget hit + a quarantine
    log.append("task2", EventKind.CONTRACT, {"task_class": "debug"})
    log.append("task2", EventKind.PLAN, {"steps": []})
    log.append("task2", EventKind.PLAN, {"steps": []})
    log.append("task2", EventKind.ESCALATION, {"rung": "change_strategy"})
    log.append("task2", EventKind.BUDGET, {"level": "hard"})
    log.append("task2", EventKind.EXPERIENCE_TRANSITION, {"state": "QUARANTINED"})
    log.append("task2", EventKind.VERIFICATION, {"tier": "T2"})
    log.append("task2", EventKind.RESULT, {"state": "FAILED", "verified": False})

    m = rebuild_metrics(log, ["task1", "task2"])
    assert m.tasks == 2
    assert m.success_rate_by_class == {"code_edit_local": 1.0, "debug": 0.0}
    assert m.rework_rate == 0.5
    assert m.verify_tier_distribution == {"T0": 1, "T2": 1}
    assert m.escalation_frequency == 0.5
    assert m.budget_exhaustion_rate == 0.5
    assert m.quarantine_events == 1
    log.close()
