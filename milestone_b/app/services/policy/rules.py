"""Policy rules — one function each, each independently unit-tested
(MILESTONE_C_PLAN.md sections 2 and 7).

Every rule takes `(proposal, grant, *, risk_globs)` and returns a `PolicyDecision`
when it fires, or `None` to fall through to the next rule. The engine
(`engine.py`) runs them in order; the first non-`None` wins. If none fire, the
engine returns ALLOW.
"""

from __future__ import annotations

import fnmatch
from urllib.parse import urlparse

from app.schemas.contracts import ActionProposal, CapabilityGrant, PolicyDecision
from app.services.capability.registry import is_side_effecting
from app.services.taint.check import blocks_side_effect


def _deny(proposal: ActionProposal, rule: str, reason: str) -> PolicyDecision:
    return PolicyDecision(
        action_id=proposal.action_id, decision="DENY", reason=reason, rule=rule
    )


def _paths_in(proposal: ActionProposal) -> list[str]:
    out: list[str] = []
    for key in ("path", "target", "file", "dir"):
        val = proposal.arguments.get(key)
        if isinstance(val, str):
            out.append(val)
    val = proposal.arguments.get("paths")
    if isinstance(val, (list, tuple)):
        out.extend(str(p) for p in val)
    return out


def rule_capability_expired(
    proposal: ActionProposal, grant: CapabilityGrant, *, risk_globs: list[str]
) -> PolicyDecision | None:
    if grant.is_expired():
        return _deny(proposal, "capability-expired", "capability grant has expired")
    return None


def rule_operation_not_granted(
    proposal: ActionProposal, grant: CapabilityGrant, *, risk_globs: list[str]
) -> PolicyDecision | None:
    if not grant.allows_operation(proposal.operation):
        return _deny(
            proposal,
            "operation-not-granted",
            f"operation {proposal.operation!r} is not in the capability grant "
            f"(token {grant.token!r} grants {sorted(grant.operations)})",
        )
    return None


def rule_path_out_of_scope(
    proposal: ActionProposal, grant: CapabilityGrant, *, risk_globs: list[str]
) -> PolicyDecision | None:
    for path in _paths_in(proposal):
        if not grant.covers_path(path):
            return _deny(
                proposal,
                "path-out-of-scope",
                f"path {path!r} escapes the capability scope {grant.scope_path!r}",
            )
    return None


def rule_tainted_side_effect(
    proposal: ActionProposal, grant: CapabilityGrant, *, risk_globs: list[str]
) -> PolicyDecision | None:
    reason = blocks_side_effect(proposal)
    if reason is not None:
        return _deny(proposal, "tainted-side-effect", reason)
    return None


def rule_egress_not_allowed(
    proposal: ActionProposal, grant: CapabilityGrant, *, risk_globs: list[str]
) -> PolicyDecision | None:
    if proposal.operation != "net.fetch":
        return None
    url = proposal.arguments.get("url", "")
    host = urlparse(url).hostname or ""
    if not host or not grant.allows_host(host):
        return _deny(
            proposal,
            "egress-not-allowed",
            f"host {host or '<none>'} is not in the per-task network allowlist "
            f"{grant.network_allowlist}",
        )
    return None


def rule_risk_class_needs_approval(
    proposal: ActionProposal, grant: CapabilityGrant, *, risk_globs: list[str]
) -> PolicyDecision | None:
    if not is_side_effecting(proposal.operation):
        return None
    for path in _paths_in(proposal):
        norm = path.replace("\\", "/")
        for glob in risk_globs:
            if fnmatch.fnmatch(norm, glob) or fnmatch.fnmatch(norm.lower(), glob):
                return PolicyDecision(
                    action_id=proposal.action_id,
                    decision="REQUIRE_APPROVAL",
                    reason=f"path {path!r} matches risk-class pattern {glob!r}",
                    rule="risk-class-approval",
                )
    return None


ORDERED_RULES = (
    rule_capability_expired,
    rule_operation_not_granted,
    rule_path_out_of_scope,
    rule_tainted_side_effect,
    rule_egress_not_allowed,
    rule_risk_class_needs_approval,
)
