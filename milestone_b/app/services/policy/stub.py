"""Policy Engine seam — slice stub.

Returns ALLOW for every proposal and logs it. The real engine
(DESIGN_TIGHTENING.md sections 4, 14.3) enforces capability scope, the untrusted
taint rule, and approvals. Milestone C replaces this class; the orchestrator call
site does not change.
"""

from __future__ import annotations

from app.schemas.contracts import ActionProposal, PolicyDecision, TaskContract


class AllowAllPolicy:
    name = "stub-allow-all"

    def decide(
        self, proposal: ActionProposal, contract: TaskContract
    ) -> PolicyDecision:
        return PolicyDecision(
            action_id=proposal.action_id,
            decision="ALLOW",
            reason="slice stub: allow + log (no capability enforcement yet)",
        )
