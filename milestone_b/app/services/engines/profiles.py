"""Expert-profile catalog (MILESTONE_N_PLAN.md §2).

The per-engine profiles come from the adapters; this adds a few domain profiles
selectable by a `"expert: <name>"` entry in `contract.constraints`.
"""

from __future__ import annotations

from app.services.engines.base import ExpertProfile

_DOMAIN: dict[str, ExpertProfile] = {
    "systems": ExpertProfile(
        name="systems",
        prompt="Systems / low-level code. Correctness under concurrency and resource limits first.",
        do=["reason about ownership, lifetime, and error paths explicitly",
            "prefer bounded buffers and explicit back-pressure",
            "make failure modes observable"],
        dont=["ignore partial failure", "allocate on a hot path without need"],
    ),
    "data-pipeline": ExpertProfile(
        name="data-pipeline",
        prompt="Data pipeline / ETL. Idempotency, schema stability, and replayability first.",
        do=["make each stage idempotent and re-runnable", "validate schema at boundaries",
            "carry provenance / lineage through the pipeline"],
        dont=["mutate source data in place", "swallow a bad record silently"],
    ),
    "web-frontend": ExpertProfile(
        name="web-frontend",
        prompt="Web frontend. Accessibility, state locality, and bundle cost matter.",
        do=["keep component state local; lift only when shared",
            "label controls and preserve keyboard/focus order",
            "guard every network read/write with loading and error states"],
        dont=["block render on a non-critical fetch", "ship a new heavy dependency for a small need"],
    ),
    "security-review": ExpertProfile(
        name="security-review",
        prompt="Security review lens. Treat all external input as hostile.",
        do=["trace every input to a trust boundary", "check authz on every state-changing path",
            "prefer allow-lists; fail closed"],
        dont=["trust client-supplied identifiers", "log secrets or PII"],
    ),
}


def domain_profile(name: str) -> ExpertProfile | None:
    return _DOMAIN.get(name.strip().lower())


def domain_names() -> list[str]:
    return sorted(_DOMAIN)


def profile_from_constraints(constraints: list[str]) -> ExpertProfile | None:
    for c in constraints:
        low = c.strip().lower()
        if low.startswith("expert:"):
            return domain_profile(low.split(":", 1)[1].strip())
    return None
