"""The one side-effecting-on-tainted check (DESIGN_TIGHTENING.md 14.3).

Used by the policy rule of the same name. Kept separate so there is a single
definition of "untrusted content may flow only into read / analyse / summarise
operations".
"""

from __future__ import annotations

from app.schemas.contracts import ActionProposal
from app.services.capability.registry import is_side_effecting
from app.services.taint.boundary import authorises


def blocks_side_effect(proposal: ActionProposal) -> str | None:
    """Reason string if the proposal must be denied for taint; else None."""
    if is_side_effecting(proposal.operation) and not authorises(proposal.trust):
        return (
            f"operation {proposal.operation!r} is side-effecting but the proposal "
            f"trust is {proposal.trust!r} (sources: {proposal.taint_sources or '[]'})"
        )
    return None
