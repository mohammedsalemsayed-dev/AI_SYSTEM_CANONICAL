"""Capability issuance.

The Orchestrator calls `issue_grant` once per plan step, **before** execution and
before any untrusted content is fetched (DESIGN_TIGHTENING.md 14.3 invariant:
authority is frozen from the trusted Plan). An unknown capability token is a plan
defect and raises — the Orchestrator turns that into a clean task failure.
"""

from __future__ import annotations

from app.schemas.contracts import CapabilityGrant, PlanStep
from app.services.capability.registry import spec_for

DEFAULT_TTL_S = 1800.0


class CapabilityError(RuntimeError):
    pass


def issue_grant(
    task_id: str,
    step: PlanStep,
    *,
    workspace_root: str,
    network_allowlist: list[str] | None = None,
    ttl_s: float = DEFAULT_TTL_S,
) -> CapabilityGrant:
    spec = spec_for(step.required_capability)
    if spec is None:
        raise CapabilityError(
            f"plan step {step.id} requires unknown capability "
            f"{step.required_capability!r}"
        )
    allowlist = list(network_allowlist or [])
    if spec.needs_network and not allowlist:
        # a network capability with no allowlist can reach nothing — that is a
        # deliberate default-deny, not an error.
        allowlist = []
    return CapabilityGrant(
        task_id=task_id,
        step_id=step.id,
        token=spec.token,
        scope_path=workspace_root,
        operations=sorted(spec.operations),
        network_allowlist=allowlist,
        ttl_s=ttl_s,
    )
