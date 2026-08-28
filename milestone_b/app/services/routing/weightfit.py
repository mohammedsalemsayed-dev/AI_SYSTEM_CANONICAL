"""Logistic-regression routing-weight fit (MILESTONE_O_PLAN.md §2, DESIGN_TIGHTENING §7.2).

stdlib only — a small deterministic batch gradient descent on the sigmoid
log-loss with L2. Label = verified success. Replaces `router.PROVISIONAL_WEIGHTS`
for a `task_class` once the selection controller flips it to data-driven.
"""

from __future__ import annotations

import math
import time

from app.schemas.contracts import WeightSet
from app.services.routing.features import FEATURE_ORDER, as_vector, feature_row

L2 = 1e-3
ITERS = 800
LR = 0.2
VAL_FRACTION = 0.2


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def training_rows(stats, registry) -> list[tuple[list[float], int]]:
    """One (feature_vector, label) per scored model_run in the stats store."""
    import json

    rows: list[tuple[list[float], int]] = []
    for m in stats._memory.all(tier="system"):  # noqa: SLF001 — same package read
        if m.kind != "model_run":
            continue
        try:
            r = json.loads(m.content)
        except Exception:  # noqa: BLE001
            continue
        model = r.get("model") or r.get("provider") or ""
        spec = registry.get(model) or _spec_by_model(registry, model)
        if spec is None:
            continue
        agg = {"n": 1, "success_rate": 1.0 if r.get("passed") else 0.0,
               "latency_median": r.get("latency_s", 0.0)}
        rows.append((as_vector(feature_row(spec, agg)), 1 if r.get("passed") else 0))
    return rows


def _spec_by_model(registry, model: str):
    for s in registry.all():
        if (s.model or s.id) == model:
            return s
    return None


def fit_weights(
    rows: list[tuple[list[float], int]],
    *,
    task_class: str = "",
    l2: float = L2,
    iters: int = ITERS,
    lr: float = LR,
    seed: int = 0,
) -> WeightSet:
    n = len(rows)
    dim = len(FEATURE_ORDER)
    if n < 3:
        return WeightSet(task_class=task_class, weights=dict.fromkeys(FEATURE_ORDER, 0.0),
                         feature_order=list(FEATURE_ORDER), n_train=n, val_accuracy=0.0,
                         degenerate=True)
    labels = {y for _, y in rows}
    degenerate = len(labels) < 2

    # deterministic index-based split
    split = max(1, int(round(n * (1 - VAL_FRACTION))))
    train, val = rows[:split], rows[split:] or rows[:1]

    w = [0.0] * dim
    for _ in range(iters):
        grad = [0.0] * dim
        for x, y in train:
            p = _sigmoid(sum(w[j] * x[j] for j in range(dim)))
            err = p - y
            for j in range(dim):
                grad[j] += err * x[j]
        m = len(train)
        for j in range(dim):
            w[j] -= lr * (grad[j] / m + l2 * w[j])

    correct = sum(
        1 for x, y in val
        if (1 if _sigmoid(sum(w[j] * x[j] for j in range(dim))) >= 0.5 else 0) == y
    )
    val_acc = correct / len(val)

    return WeightSet(
        task_class=task_class,
        weights={FEATURE_ORDER[j]: round(w[j], 6) for j in range(dim)},
        feature_order=list(FEATURE_ORDER),
        n_train=len(train), val_accuracy=round(val_acc, 4),
        fitted_ts=time.time(), degenerate=degenerate,
    )


def _logit(ws: WeightSet, feats: dict[str, float]) -> float:
    return sum(ws.weights.get(k, 0.0) * float(feats.get(k, 0.0)) for k in FEATURE_ORDER)


def predict(ws: WeightSet, feats: dict[str, float]) -> float:
    return _sigmoid(_logit(ws, feats))


def score(ws: WeightSet, feats: dict[str, float]) -> float:
    """The router's ranking scalar for a candidate — the raw logit (monotone in
    predicted success)."""
    return _logit(ws, feats)
