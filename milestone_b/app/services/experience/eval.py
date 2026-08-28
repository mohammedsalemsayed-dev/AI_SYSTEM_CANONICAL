"""Stub offline evaluation for the VALIDATED -> PROMOTED gate
(MILESTONE_F_PLAN.md §5 days 9-10, §3, DESIGN_TIGHTENING §8).

The real held-out eval harness lands in Milestone I. Milestone F ships:
  * a small canonical guardrail task set (a fixture, not live tasks),
  * a deterministic stub `run_offline_eval` that replays an experience's
    recorded outcome against that set and returns a held-out count + a
    guardrail-drop measurement,
  * `promote_decision`, which combines the numeric gate with a
    human-approval branch for security / policy / execution-scope strategies.

Everything here is wired so the VALIDATED -> PROMOTED state machine is
complete and testable now; only the eval body is a stub.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.contracts import ExperienceRecord
from app.services.experience.lifecycle import (
    MAX_GUARDRAIL_DROP_PP,
    MIN_HELDOUT,
    gate_validated_to_promoted,
)

# ~canonical guardrail tasks (a fixture set; Milestone I replaces with real ones).
# Each entry: a signature fragment the strategy must not regress, and the
# baseline verified-success rate the guardrail run is compared against.
GUARDRAIL_SET: list[dict] = [
    {"name": "code_edit_local/off-by-one", "task_class": "code_edit_local", "baseline": 1.0},
    {"name": "code_edit_local/empty-input", "task_class": "code_edit_local", "baseline": 1.0},
    {"name": "code_edit_local/null-guard", "task_class": "code_edit_local", "baseline": 1.0},
    {"name": "debug/stack-trace", "task_class": "debug", "baseline": 0.9},
    {"name": "debug/regression", "task_class": "debug", "baseline": 0.9},
    {"name": "refactor/rename", "task_class": "refactor", "baseline": 1.0},
    {"name": "refactor/extract", "task_class": "refactor", "baseline": 0.95},
    {"name": "test_authoring/unit", "task_class": "test_authoring", "baseline": 1.0},
]

# strategies that touch these need a human before PROMOTED regardless of numbers
_SECURITY_MARKERS = ("auth", "security", "policy", "capability", "sandbox", "egress", "secret")


@dataclass
class EvalResult:
    heldout_n: int
    guardrail_drop_pp: float
    detail: str


def run_offline_eval(exp: ExperienceRecord, guardrail_set: list[dict] | None = None) -> EvalResult:
    """Deterministic stub. Held-out count comes from the experience's own shadow
    history (each distinct shadow task is a held-out sample here); the guardrail
    drop is the mean baseline minus the strategy's observed shadow success,
    clamped at 0. A strategy with no shadow history evaluates as 0 held-out."""
    gset = guardrail_set if guardrail_set is not None else GUARDRAIL_SET
    log = exp.shadow_replay_log
    heldout_n = len({(r.get("week"), i) for i, r in enumerate(log)})
    if log:
        observed = sum(1 for r in log if r.get("verified")) / len(log)
    else:
        observed = 0.0
    baseline = sum(g["baseline"] for g in gset) / len(gset)
    drop_pp = max(0.0, (baseline - observed) * 100.0)
    return EvalResult(
        heldout_n=heldout_n,
        guardrail_drop_pp=round(drop_pp, 2),
        detail=f"observed {observed:.0%} vs guardrail baseline {baseline:.0%} over {len(log)} shadow tasks",
    )


def touches_security(exp: ExperienceRecord) -> bool:
    hay = f"{exp.signature} {exp.strategy} {' '.join(exp.actions)}".lower()
    return any(m in hay for m in _SECURITY_MARKERS)


@dataclass
class PromoteDecision:
    ok: bool
    needs_human: bool
    why: str


def promote_decision(
    exp: ExperienceRecord,
    *,
    eval_result: EvalResult | None = None,
    human_approved: bool = False,
) -> PromoteDecision:
    """Fold the offline eval into the experience, then apply the §8 gate plus the
    security human-approval branch. Does not mutate lifecycle state."""
    ev = eval_result or run_offline_eval(exp)
    exp.monitoring_metrics["heldout_n"] = ev.heldout_n
    exp.guardrail_result = ev.guardrail_drop_pp

    numeric_ok, why = gate_validated_to_promoted(exp)
    if not numeric_ok:
        return PromoteDecision(ok=False, needs_human=False, why=why)
    if touches_security(exp) and not human_approved:
        return PromoteDecision(
            ok=False, needs_human=True,
            why="security/policy/execution-scope strategy: human approval required",
        )
    return PromoteDecision(
        ok=True, needs_human=False,
        why=f"held-out {ev.heldout_n} >= {MIN_HELDOUT}, guardrail drop "
        f"{ev.guardrail_drop_pp:.1f}pp <= {MAX_GUARDRAIL_DROP_PP}pp"
        + (" (human-approved)" if touches_security(exp) else ""),
    )
