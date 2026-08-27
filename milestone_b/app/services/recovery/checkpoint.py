"""Checkpoint (MILESTONE_D_PLAN.md §2).

A resumable marker folded from the event log: the last canonical state, the
changed-path manifest so far, how many steps completed, and any side-effecting
action that was proposed but has no confirming observation (an uncertain
external effect).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.events.log import EventKind
from app.schemas.contracts import new_id
from app.services.capability.registry import SIDE_EFFECTING_OPS
from app.services.recovery.idempotency import completed_idempotency_keys

# operations whose effects reach outside the workspace copy; a proposal for one
# of these without a matching observation is "uncertain"
_EXTERNAL_OPS = {"net.fetch", "secret.use"}


class Checkpoint(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ckpt"))
    task_id: str
    canonical_state: str = "CREATED"
    step_index: int = 0
    changed_paths: list[str] = Field(default_factory=list)
    completed_keys: list[str] = Field(default_factory=list)
    uncertain_external_actions: list[str] = Field(default_factory=list)


def build_checkpoint(events: list) -> Checkpoint:
    if not events:
        raise ValueError("no events")
    task_id = events[0].task_id
    state = "CREATED"
    changed: set[str] = set()
    steps = 0
    seen_obs_steps: set[str] = set()
    proposals: list[dict] = []

    for e in events:
        if e.kind == EventKind.STATE:
            state = e.payload["state"]
        elif e.kind == EventKind.ARTIFACT:
            changed.update(e.payload.get("changed_paths", []))
        elif e.kind == EventKind.OBSERVATION:
            steps += 1
            seen_obs_steps.add(e.payload.get("step_id"))
        elif e.kind == EventKind.ACTION_PROPOSAL:
            proposals.append(e.payload)

    uncertain = [
        p["action_id"]
        for p in proposals
        if p.get("operation") in (_EXTERNAL_OPS & SIDE_EFFECTING_OPS)
        and p.get("step_id") not in seen_obs_steps
    ]

    return Checkpoint(
        task_id=task_id,
        canonical_state=state,
        step_index=steps,
        changed_paths=sorted(changed),
        completed_keys=sorted(completed_idempotency_keys(events)),
        uncertain_external_actions=uncertain,
    )
