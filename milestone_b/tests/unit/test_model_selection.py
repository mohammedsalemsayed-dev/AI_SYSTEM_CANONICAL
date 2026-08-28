"""Acceptance (Unit): routing features, logistic weight fit, selection controller
(MILESTONE_O_PLAN.md §6)."""

from __future__ import annotations

import random

from app.schemas.contracts import ProviderSpec, WeightSet
from app.services.memory.store import MemoryStore
from app.services.routing.features import FEATURE_ORDER, feature_row
from app.services.routing.registry import ProviderRegistry
from app.services.routing.selection import (
    MIN_TRAIN,
    MIN_VAL_ACC,
    ModelSelectionController,
)
from app.services.routing.weightfit import fit_weights, predict, score


# --- features --------------------------------------------------- #
def test_feature_row_reflects_eligibility() -> None:
    spec = ProviderSpec(id="m", provider="x", model="m", quality_prior=0.6,
                        latency_prior_s=12, privacy_score=0.4, resource_cost=0.1, local=False)
    prior = feature_row(spec, None)
    assert prior["quality"] == 0.6 and prior["local"] == 0.0 and prior["bias"] == 1.0
    measured = feature_row(spec, {"n": 30, "success_rate": 0.9, "latency_median": 6.0})
    assert measured["quality"] == 0.9 and measured["latency"] == 0.1
    assert list(prior) == list(FEATURE_ORDER)


# --- weight fit ---------------------------------------------- #
def _separable(n: int, seed: int = 0) -> list[tuple[list[float], int]]:
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        q = rng.uniform(0, 1)
        rows.append(([q, rng.uniform(0, .5), 0.0, rng.uniform(0, .5),
                      rng.uniform(0, 1), float(rng.random() < .3), 1.0],
                     1 if q > 0.55 else 0))
    return rows


def test_fit_converges_and_is_deterministic() -> None:
    rows = _separable(200)
    a = fit_weights(rows, task_class="code_edit_local")
    b = fit_weights(rows, task_class="code_edit_local")
    assert a.weights == b.weights
    assert a.val_accuracy >= 0.95 and not a.degenerate
    hi = predict(a, dict(zip(FEATURE_ORDER, [0.9, 0.1, 0, 0.1, 0.5, 0, 1])))
    lo = predict(a, dict(zip(FEATURE_ORDER, [0.2, 0.1, 0, 0.1, 0.5, 0, 1])))
    assert hi > 0.7 > lo and 0.0 <= lo <= 1.0


def test_fit_handles_tiny_and_degenerate_input() -> None:
    tiny = fit_weights([([0.5] * 7, 1), ([0.4] * 7, 0)], task_class="x")
    assert tiny.degenerate and tiny.n_train == 2
    same = fit_weights([([random.random() for _ in range(7)], 1) for _ in range(50)], task_class="x")
    assert same.degenerate  # all one label


# --- selection controller ---------------------------------- #
class _Stats:
    def __init__(self, eligible: list[str]) -> None:
        self._e = eligible

    def eligible_models(self, task_class: str) -> list[str]:
        return list(self._e)


def _ws(n_train: int, val_acc: float, degenerate: bool = False) -> WeightSet:
    return WeightSet(task_class="code_edit_local", weights=dict.fromkeys(FEATURE_ORDER, 0.1),
                     feature_order=list(FEATURE_ORDER), n_train=n_train,
                     val_accuracy=val_acc, degenerate=degenerate)


def test_controller_stays_static_until_all_conditions_hold() -> None:
    mem = MemoryStore()
    reg = ProviderRegistry()
    c = ModelSelectionController(mem, _Stats(["a"]), reg)
    assert c.evaluate("code_edit_local").mode == "static"          # 1 eligible

    c = ModelSelectionController(mem, _Stats(["a", "b"]), reg)
    assert c.evaluate("code_edit_local").mode == "static"          # no weight set

    c.set_weights(_ws(n_train=10, val_acc=0.9))
    assert c.evaluate("code_edit_local").mode == "static"          # n_train < MIN_TRAIN

    c.set_weights(_ws(n_train=MIN_TRAIN + 5, val_acc=MIN_VAL_ACC - 0.1))
    assert c.evaluate("code_edit_local").mode == "static"          # val_acc low

    c.set_weights(_ws(n_train=MIN_TRAIN + 5, val_acc=0.9))
    assert c.evaluate("code_edit_local").mode == "data_driven"

    # a failing regression check blocks it
    class _Reg:
        passed = False
        why = "guardrail dropped"

    assert c.evaluate("code_edit_local", regression_check=lambda: _Reg()).mode == "static"
    mem.close()


def test_promote_then_demote_persists_and_reverts() -> None:
    mem = MemoryStore()
    c = ModelSelectionController(mem, _Stats(["a", "b"]), ProviderRegistry())
    c.set_weights(_ws(n_train=MIN_TRAIN + 5, val_acc=0.9))
    c.promote("code_edit_local")
    assert ModelSelectionController(mem, _Stats(["a", "b"]), ProviderRegistry()).mode("code_edit_local") == "data_driven"
    c.demote("code_edit_local", "canary rollback")
    assert c.mode("code_edit_local") == "static"
    mem.close()


# --- router integration ---------------------------------- #
def test_router_uses_fitted_weights_when_data_driven() -> None:
    from app.services.routing.router import Router

    specs = [
        ProviderSpec(id="hi", provider="x", model="hi", quality_prior=0.9, available=True),
        ProviderSpec(id="lo", provider="y", model="lo", quality_prior=0.4, available=True),
    ]
    reg = ProviderRegistry(specs)
    mem = MemoryStore()
    # weight set that *only* rewards the 'local' feature -> neither is local -> tie -> id order
    ctrl = ModelSelectionController(mem, _Stats(["hi", "lo"]), reg)
    inverted = _ws(n_train=MIN_TRAIN + 5, val_acc=0.9)
    inverted.weights = {**dict.fromkeys(FEATURE_ORDER, 0.0), "quality": -5.0, "bias": 0.0}
    ctrl.set_weights(inverted)
    ctrl._put("selection_mode", "code_edit_local", {"mode": "data_driven", "why": "test"})

    r = Router(reg, seed=0, epsilon=0.0, selection=ctrl)
    # data-driven with an inverted quality weight -> prefers the *low* quality model
    s_hi = r._score(reg.require("hi"), "code_edit_local", "NORMAL")
    s_lo = r._score(reg.require("lo"), "code_edit_local", "NORMAL")
    assert s_lo > s_hi
    mem.close()
