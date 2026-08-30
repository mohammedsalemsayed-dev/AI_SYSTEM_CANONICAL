"""Policy Engine (MILESTONE_C_PLAN.md section 2). Replaces `stub.AllowAllPolicy`.

Deterministic: runs the ordered rules from `rules.py`; first non-`None` wins;
ALLOW if none fire. No model call. The orchestrator call site is unchanged except
that it now passes the `CapabilityGrant`.
"""

from __future__ import annotations

from app.schemas.contracts import (
    ActionProposal,
    CapabilityGrant,
    PolicyDecision,
    TaskContract,
)
from app.services.policy.rules import ORDERED_RULES

# Side-effecting writes under these paths need a human approval
# (design-notes 14.1 permanent-gate note).
DEFAULT_RISK_GLOBS = [
    "*auth*",
    "*/auth/*",
    "*/migrations/*",
    "*secret*",
    "*/.github/*",
    "*/payments/*",
    "*/billing/*",
    "*.pem",
    "*.key",
]


class PolicyEngine:
    name = "milestone-c"

    def __init__(self, risk_globs: list[str] | None = None) -> None:
        self.risk_globs = list(risk_globs) if risk_globs is not None else list(DEFAULT_RISK_GLOBS)

    def decide(
        self,
        proposal: ActionProposal,
        contract: TaskContract,
        grant: CapabilityGrant | None = None,
    ) -> PolicyDecision:
        if grant is None:
            return PolicyDecision(
                action_id=proposal.action_id,
                decision="DENY",
                reason="no capability grant supplied for this proposal",
                rule="no-grant",
            )
        for rule in ORDERED_RULES:
            decision = rule(proposal, grant, risk_globs=self.risk_globs)
            if decision is not None:
                return decision
        return PolicyDecision(
            action_id=proposal.action_id,
            decision="ALLOW",
            reason="all policy rules passed",
            rule="default-allow",
        )
