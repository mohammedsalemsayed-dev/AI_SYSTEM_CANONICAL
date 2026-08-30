"""Regression protection over the frozen guardrail suite
(MILESTONE_I_PLAN.md §2, design-notes §8).

A stored baseline `SuiteResult` + a gate that blocks any promotion whose guardrail
aggregate drops more than `MAX_GUARDRAIL_DROP_PP` points **or** that makes a
previously-passing guardrail task fail. The baseline lives on the system memory
tier as an event-like record, never silently overwritten.
"""

from __future__ import annotations

import json
import time

from app.schemas.contracts import MemoryRecord, RegressionResult, SuiteResult

# shared with design-notes §8 (experience VALIDATED -> PROMOTED)
MAX_GUARDRAIL_DROP_PP = 2.0
BASELINE_MAX_AGE_S = 30 * 24 * 3600


def check_regression(candidate: SuiteResult, baseline: SuiteResult) -> RegressionResult:
    base_fail = set(baseline.failures)
    cand_fail = set(candidate.failures)
    newly_failing = sorted(cand_fail - base_fail)
    recovered = sorted(base_fail - cand_fail)
    drop_pp = (baseline.pass_rate - candidate.pass_rate) * 100.0
    passed = (drop_pp <= MAX_GUARDRAIL_DROP_PP) and not newly_failing
    if passed:
        why = f"guardrail held ({candidate.pass_rate:.0%} vs baseline {baseline.pass_rate:.0%})"
    elif newly_failing:
        why = f"newly-failing guardrail task(s): {', '.join(newly_failing)}"
    else:
        why = f"guardrail dropped {drop_pp:.1f}pp (> {MAX_GUARDRAIL_DROP_PP}pp)"
    return RegressionResult(
        passed=passed, drop_pp=round(drop_pp, 2), newly_failing=newly_failing,
        recovered=recovered, baseline_rate=baseline.pass_rate,
        candidate_rate=candidate.pass_rate, why=why,
    )


class RegressionBaseline:
    """Stored guardrail baseline on the system memory tier."""

    def __init__(self, memory) -> None:
        self._memory = memory

    def set_baseline(self, result: SuiteResult) -> SuiteResult:
        self._memory.put(
            MemoryRecord(
                tier="system", kind="regression_baseline", scope="guardrail",
                trust="workspace", content=result.model_dump_json(),
            )
        )
        return result

    def latest(self) -> SuiteResult | None:
        rows = [
            m for m in self._memory.all(tier="system")
            if m.kind == "regression_baseline" and m.scope == "guardrail"
        ]
        return SuiteResult.model_validate_json(rows[-1].content) if rows else None

    def is_stale(self, now: float | None = None) -> bool:
        b = self.latest()
        if b is None:
            return True
        return (now or time.time()) - b.ts > BASELINE_MAX_AGE_S

    def certify(self, candidate: SuiteResult) -> RegressionResult:
        """Gate a candidate against the stored baseline. No baseline -> cannot
        certify (fails closed)."""
        base = self.latest()
        if base is None:
            return RegressionResult(
                passed=False, why="no guardrail baseline recorded; cannot certify"
            )
        return check_regression(candidate, base)
