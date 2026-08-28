"""Offline evaluation for a promotion (MILESTONE_I_PLAN.md §2, DESIGN_TIGHTENING §8).

Replay a held-out task subset twice — once with the candidate change applied
(an experience's strategy injected as an advisory note; a routing weight set; a
role enabled) and once without — compare verified success, then run the frozen
guardrail suite through the regression gate. `decision == "promote"` only when
the held-out delta is non-negative AND the guardrail line holds. A change that
touches security / policy / execution scope still carries the §8 human-approval
branch.

The `run_with` / `run_without` / `run_guardrail` callables are injected, so the
decision logic is deterministic and unit-testable; production wires them to real
orchestrator runs.
"""

from __future__ import annotations

from typing import Callable, Sequence

from app.schemas.contracts import EvalReport, RegressionResult, SuiteResult

MIN_HELDOUT = 10  # §8
_SECURITY_MARKERS = ("auth", "security", "policy", "capability", "sandbox", "egress", "secret")


def _rate(results: Sequence[bool]) -> float:
    return sum(1 for r in results if r) / len(results) if results else 0.0


def touches_security(*text: str) -> bool:
    hay = " ".join(text).lower()
    return any(m in hay for m in _SECURITY_MARKERS)


class OfflineEval:
    def __init__(
        self,
        run_with: Callable[[str], bool],
        run_without: Callable[[str], bool],
        *,
        certify_guardrail: Callable[[SuiteResult], RegressionResult] | None = None,
        run_guardrail: Callable[[], SuiteResult] | None = None,
    ) -> None:
        self._with = run_with
        self._without = run_without
        self._certify = certify_guardrail
        self._run_guardrail = run_guardrail

    def evaluate(
        self,
        subject: str,
        heldout_task_ids: list[str],
        *,
        kind: str = "experience",
        security_context: str = "",
        human_approved: bool = False,
    ) -> EvalReport:
        with_res = [self._with(tid) for tid in heldout_task_ids]
        without_res = [self._without(tid) for tid in heldout_task_ids]
        w, wo = _rate(with_res), _rate(without_res)
        delta = round(w - wo, 4)

        guardrail: RegressionResult | None = None
        if self._certify is not None and self._run_guardrail is not None:
            guardrail = self._certify(self._run_guardrail())

        enough = len(heldout_task_ids) >= MIN_HELDOUT
        gr_ok = guardrail is None or guardrail.passed
        promote = enough and delta >= 0.0 and gr_ok

        needs_human = promote and touches_security(subject, security_context) and not human_approved
        decision = "promote" if (promote and not needs_human) else "hold"

        if not enough:
            why = f"only {len(heldout_task_ids)}/{MIN_HELDOUT} held-out tasks"
        elif delta < 0.0:
            why = f"held-out success dropped {(-delta) * 100:.1f}pp"
        elif not gr_ok:
            why = f"guardrail gate failed: {guardrail.why}"  # type: ignore[union-attr]
        elif needs_human:
            why = "security/policy/execution-scope change: human approval required"
        else:
            why = f"held-out +{delta * 100:.1f}pp and guardrail held"

        return EvalReport(
            subject=subject, kind=kind, heldout_n=len(heldout_task_ids),
            with_success=w, without_success=wo, delta=delta, guardrail=guardrail,
            decision=decision, needs_human=needs_human, why=why,
        )
