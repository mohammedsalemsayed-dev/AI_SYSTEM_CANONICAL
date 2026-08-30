"""Idempotency (MILESTONE_D_PLAN.md §2).

A step whose `ActionProposal` has a matching successful `Observation` in the log
has already run — its `idempotency_key` is "completed". On resume the orchestrator
does not re-execute completed keys (in the slice the builder always works on a
fresh copy, so the guarantee is really "no double external effect"; the key set
also tells `reconcile` how far the task got).
"""

from __future__ import annotations

from app.events.log import EventKind


def completed_idempotency_keys(events: list) -> set[str]:
    proposals_by_step: dict[str, dict] = {}
    for e in events:
        if e.kind == EventKind.ACTION_PROPOSAL:
            proposals_by_step[e.payload["step_id"]] = e.payload

    done: set[str] = set()
    for e in events:
        if e.kind != EventKind.OBSERVATION:
            continue
        p = e.payload
        if p.get("error") or p.get("exit_code", 0) != 0:
            continue
        prop = proposals_by_step.get(p.get("step_id"))
        if prop:
            done.add(prop["idempotency_key"])
    return done
