"""Routing feature vector (MILESTONE_O_PLAN.md §2, DESIGN_TIGHTENING §7.2).

One ordered feature dict per `(task_class, model)` candidate. When the model is
eligible its measured aggregates replace the priors.
"""

from __future__ import annotations

from app.schemas.contracts import ProviderSpec

FEATURE_ORDER = ("quality", "latency", "cost", "resource", "privacy", "local", "bias")


def feature_row(spec: ProviderSpec, agg: dict | None = None) -> dict[str, float]:
    quality = spec.quality_prior
    latency = spec.latency_prior_s
    if agg and agg.get("n", 0) > 0:
        quality = agg.get("success_rate", quality)
        latency = agg.get("latency_median") or latency
    return {
        "quality": float(quality),
        "latency": float(latency) / 60.0,
        "cost": float(spec.cost_prior_usd),
        "resource": float(spec.resource_cost),
        "privacy": float(spec.privacy_score),
        "local": 1.0 if spec.local else 0.0,
        "bias": 1.0,
    }


def as_vector(row: dict[str, float]) -> list[float]:
    return [row.get(k, 0.0) for k in FEATURE_ORDER]
