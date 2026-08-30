"""Policy Engine seam — slice stub.

Returns ALLOW for every proposal and logs it. The real engine
(design-notes sections 4, 14.3) enforces capability scope, the untrusted
taint rule, and approvals. Milestone C replaces this class; the orchestrator call
site does not change.
"""

from __future__ import annotations

from app.schemas.contracts import (
    ActionProposal,
    CapabilityGrant,
    PolicyDecision,
    TaskContract,
)


class AllowAllPolicy:
    """Milestone B stub, kept as an opt-in test double. Milestone C's real engine
    is `app.services.policy.engine.PolicyEngine`."""

    name = "stub-allow-all"

    def decide(
        self,
        proposal: ActionProposal,
        contract: TaskContract,
        grant: CapabilityGrant | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            action_id=proposal.action_id,
            decision="ALLOW",
            reason="stub: allow + log (no enforcement)",
            rule="stub-allow-all",
        )
