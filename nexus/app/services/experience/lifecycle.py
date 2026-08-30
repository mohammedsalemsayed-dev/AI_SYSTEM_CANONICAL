"""Experience lifecycle gates (MILESTONE_F_PLAN.md §2, §7; design-notes §8).

OBSERVED -> CANDIDATE -> VALIDATED -> PROMOTED -> MONITORED -> STALE / QUARANTINED.
Each transition is a numeric gate; every value here is a §8 starting point.
"""

from __future__ import annotations

from app.schemas.contracts import ExperienceRecord

# §8 tunables
MIN_SHADOW_TASKS = 5
MIN_SHADOW_SUCCESS = 0.80
MAX_COST_RATIO = 1.20
MIN_DISTINCT_WEEKS = 3
MIN_HELDOUT = 10
MAX_GUARDRAIL_DROP_PP = 2.0
STALE_TRAILING_N = 20
STALE_SUCCESS = 0.70
STALE_MIN_USES_60D = 3
QUARANTINE_TRAILING_N = 5
QUARANTINE_SUCCESS = 0.40

ALLOWED: dict[str, set[str]] = {
    "OBSERVED": {"CANDIDATE", "QUARANTINED"},
    "CANDIDATE": {"VALIDATED", "QUARANTINED"},
    "VALIDATED": {"PROMOTED", "QUARANTINED"},
    "PROMOTED": {"MONITORED", "STALE", "QUARANTINED"},
    "MONITORED": {"STALE", "QUARANTINED"},
    "STALE": set(),
    "QUARANTINED": set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED.get(current, set())


def gate_observed_to_candidate(
    *, verify_tier: str, is_new_signature_strategy: bool
) -> tuple[bool, str]:
    if verify_tier not in ("T0", "T1", "T2", "T3"):
        return False, f"unknown verify tier {verify_tier!r}"
    if verify_tier == "T3":
        return True, "T3"  # human-verified
    if verify_tier not in ("T1", "T2", "T0"):
        return False, "verify tier below T0"
    if not is_new_signature_strategy:
        return False, "(signature, strategy) already represented"
    return True, f"completed at {verify_tier}"


def gate_candidate_to_validated(exp: ExperienceRecord) -> tuple[bool, str]:
    log = exp.shadow_replay_log
    if len(log) < MIN_SHADOW_TASKS:
        return False, f"only {len(log)}/{MIN_SHADOW_TASKS} shadow tasks"
    successes = sum(1 for r in log if r.get("verified"))
    rate = successes / len(log)
    if rate < MIN_SHADOW_SUCCESS:
        return False, f"shadow success {rate:.0%} < {MIN_SHADOW_SUCCESS:.0%}"
    costs = [r.get("cost_ratio", 1.0) for r in log]
    med = sorted(costs)[len(costs) // 2]
    if med > MAX_COST_RATIO:
        return False, f"median cost ratio {med:.2f} > {MAX_COST_RATIO}"
    weeks = {r.get("week") for r in log if r.get("week") is not None}
    if len(weeks) < MIN_DISTINCT_WEEKS:
        return False, f"only {len(weeks)}/{MIN_DISTINCT_WEEKS} distinct weeks"
    return True, f"{rate:.0%} over {len(log)} shadow tasks"


def gate_validated_to_promoted(exp: ExperienceRecord) -> tuple[bool, str]:
    m = exp.monitoring_metrics
    heldout = m.get("heldout_n", 0)
    if heldout < MIN_HELDOUT:
        return False, f"only {heldout}/{MIN_HELDOUT} held-out tasks"
    if exp.guardrail_result is None:
        return False, "no guardrail result"
    if exp.guardrail_result > MAX_GUARDRAIL_DROP_PP:
        return False, f"guardrail drop {exp.guardrail_result:.1f}pp > {MAX_GUARDRAIL_DROP_PP}pp"
    return True, "held-out + guardrail passed"


def should_go_stale(exp: ExperienceRecord) -> tuple[bool, str]:
    m = exp.monitoring_metrics
    n = int(m.get("trailing_n", 0))
    if n >= STALE_TRAILING_N and m.get("trailing_success", 1.0) < STALE_SUCCESS:
        return True, f"trailing-{n} success {m['trailing_success']:.0%} < {STALE_SUCCESS:.0%}"
    if m.get("uses_60d", 99) < STALE_MIN_USES_60D:
        return True, f"only {m.get('uses_60d')} uses in 60 days"
    if m.get("dependency_missing"):
        return True, "a named dependency no longer exists"
    return False, ""


def should_quarantine(exp: ExperienceRecord, *, catastrophic: bool = False) -> tuple[bool, str]:
    if catastrophic:
        return True, "catastrophic outcome"
    m = exp.monitoring_metrics
    n = int(m.get("trailing_n", 0))
    if n >= QUARANTINE_TRAILING_N and m.get("trailing_success", 1.0) < QUARANTINE_SUCCESS:
        return True, f"trailing-{n} success {m['trailing_success']:.0%} < {QUARANTINE_SUCCESS:.0%}"
    return False, ""
