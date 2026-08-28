"""Router — static table, then data-driven once models are eligible
(DESIGN_TIGHTENING §7).

Order of decision:
  1. hardware EMERGENCY -> pause (provider_id == "").
  2. static default from `table.py` (first available id in `prefer`, skipping
     ids already `tried`).
  3. escalation trigger fired, or hardware biases local -> override the static
     pick (best cloud by quality, or best available local / cheapest cloud).
  4. >= 1 eligible model for the class -> score eligible available candidates
     with the PROVISIONAL weights blended with measured stats; displace the
     static pick only if it wins by >= STABILITY_MARGIN.
  5. below eligibility, with probability EPSILON, explore a different available
     candidate (seeded RNG so tests are deterministic).
"""

from __future__ import annotations

import random

from app.schemas.contracts import ProviderSpec, RouteDecision
from app.services.hardware.modes import biases_local, should_pause
from app.services.routing.registry import ProviderRegistry
from app.services.routing.table import escalation_reason, policy_for

EPSILON = 0.15
STABILITY_MARGIN = 0.05

# provisional, hand-tuned; Milestone I replaces these with a logistic-regression fit
PROVISIONAL_WEIGHTS = {
    "quality": 4.0, "privacy": 2.0, "latency": -1.5, "cost": -2.0, "resource": -2.0,
    "local_bonus": 1.0,
}


class Router:
    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        stats=None,
        *,
        epsilon: float = EPSILON,
        seed: int | None = None,
    ) -> None:
        self.registry = registry or ProviderRegistry()
        self.stats = stats
        self.epsilon = epsilon
        self._rng = random.Random(seed)

    # -- public ---------------------------------------------------- #
    def route(
        self,
        task_class: str,
        role: str = "builder",
        *,
        task_id: str = "",
        attempt: int = 0,
        hardware_mode: str = "NORMAL",
        context_tokens: int = 0,
        risk_level: str = "low",
        tried: list[str] | None = None,
        modules_touched: int = 0,
        user_requested_cloud: bool = False,
        high_stakes: bool = False,
        contradiction_unresolved: bool = False,
    ) -> RouteDecision:
        tried = tried or []
        avail = [s for s in self.registry.available() if s.id not in tried]
        base = RouteDecision(
            task_id=task_id, role=role, task_class=task_class,
            hardware_mode=hardware_mode,
            candidates_considered=[s.id for s in avail],
        )

        if should_pause(hardware_mode):
            base.reason = f"paused: hardware mode {hardware_mode}"
            return base
        if not avail:
            # everything already tried — fall back to the raw default, tried or not
            base.provider_id = policy_for(task_class).prefer[0]
            base.reason = "all candidates already tried; reusing the default"
            return base

        reason = escalation_reason(
            task_class, attempt=attempt, context_tokens=context_tokens,
            risk_level=risk_level, modules_touched=modules_touched,
            contradiction_unresolved=contradiction_unresolved,
            user_requested_cloud=user_requested_cloud, high_stakes=high_stakes,
        )
        pick, why, escalated = self._static_pick(task_class, avail, reason, hardware_mode)

        dd = self._data_driven_pick(task_class, avail, hardware_mode)
        if dd is not None and dd[0].id != pick.id and dd[1] >= self._score(pick, task_class, hardware_mode) + STABILITY_MARGIN:
            base.provider_id, base.reason, base.data_driven = dd[0].id, (
                f"data-driven: {dd[0].id} scores {dd[1]:.2f} (>= static +{STABILITY_MARGIN})"
            ), True
            return base

        # epsilon exploration only when the static pick is not itself eligible
        if (
            not escalated
            and self.stats is not None
            and not self.stats.eligible(task_class, pick.model or pick.id)
            and len(avail) > 1
            and self._rng.random() < self.epsilon
        ):
            others = [s for s in avail if s.id != pick.id]
            chosen = self._rng.choice(others)
            base.provider_id, base.reason, base.explored = chosen.id, (
                f"exploration (epsilon={self.epsilon}): trying {chosen.id} instead of {pick.id}"
            ), True
            return base

        base.provider_id, base.reason, base.escalated = pick.id, why, escalated
        return base

    def spec(self, provider_id: str) -> ProviderSpec:
        return self.registry.require(provider_id)

    # -- internals ----------------------------------------------- #
    def _static_pick(self, task_class, avail, reason, hardware_mode):
        pol = policy_for(task_class)
        avail_ids = {s.id for s in avail}

        if biases_local(hardware_mode):
            locals_ = [s for s in avail if s.local]
            if locals_:
                best = max(locals_, key=lambda s: s.quality_prior)
                return best, f"hardware {hardware_mode}: prefer local ({best.id})", False
            cheapest = min(avail, key=lambda s: (s.cost_prior_usd, s.resource_cost))
            return cheapest, f"hardware {hardware_mode}: no local available, cheapest cloud", False

        if reason is not None:
            clouds = [s for s in avail if not s.local]
            if clouds:
                best = max(clouds, key=lambda s: s.quality_prior)
                return best, f"escalated to cloud ({reason})", True

        for pid in pol.prefer:
            if pid in avail_ids:
                return self.registry.require(pid), f"static table default for {task_class}", False
        # nothing in prefer is available -> best available cloud, else best available
        clouds = [s for s in avail if not s.local]
        pool = clouds or avail
        best = max(pool, key=lambda s: s.quality_prior)
        return best, f"static default unavailable; best available ({best.id})", False

    def _data_driven_pick(self, task_class, avail, hardware_mode):
        if self.stats is None:
            return None
        scored = [
            (s, self._score(s, task_class, hardware_mode))
            for s in avail
            if self.stats.eligible(task_class, s.model or s.id)
            and not getattr(self.stats, "is_frozen", lambda *_: False)(task_class, s.model or s.id)
        ]
        if not scored:
            return None
        return max(scored, key=lambda t: t[1])

    def _score(self, spec: ProviderSpec, task_class: str, hardware_mode: str) -> float:
        w = PROVISIONAL_WEIGHTS
        quality = spec.quality_prior
        latency = spec.latency_prior_s
        if self.stats is not None and self.stats.eligible(task_class, spec.model or spec.id):
            agg = self.stats.aggregate(task_class, spec.model or spec.id)
            quality = agg["success_rate"]
            latency = agg["latency_median"] or latency
        local_bonus = w["local_bonus"] if (spec.local and biases_local(hardware_mode)) else 0.0
        return (
            w["quality"] * quality
            + w["privacy"] * spec.privacy_score
            + w["latency"] * (latency / 60.0)
            + w["cost"] * spec.cost_prior_usd
            + w["resource"] * spec.resource_cost
            + local_bonus
        )
