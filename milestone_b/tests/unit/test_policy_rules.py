"""Acceptance (Unit): each policy rule in isolation + engine ordering
(MILESTONE_C_PLAN.md section 7)."""

from __future__ import annotations

from app.schemas.contracts import ActionProposal, CapabilityGrant, TaskContract
from app.services.policy.engine import PolicyEngine

_CONTRACT = TaskContract(task_id="t", original_request="r", objective="o")


def _grant(**kw) -> CapabilityGrant:
    base = dict(
        task_id="t",
        scope_path="/ws",
        operations=["file.read", "file.write", "file.create", "dir.list"],
        network_allowlist=[],
        ttl_s=3600.0,
    )
    base.update(kw)
    return CapabilityGrant(**base)


def _proposal(**kw) -> ActionProposal:
    base = dict(
        task_id="t",
        step_id="s1",
        operation="file.write",
        arguments={"path": "/ws/src/a.py"},
        required_capability="fs.write",
        workspace_scope="/ws",
        expected_effect="edit",
        idempotency_key="t:s1",
    )
    base.update(kw)
    return ActionProposal(**base)


def decide(proposal, grant):
    return PolicyEngine().decide(proposal, _CONTRACT, grant)


def test_allow_when_all_rules_pass() -> None:
    d = decide(_proposal(), _grant())
    assert d.decision == "ALLOW" and d.rule == "default-allow"


def test_deny_without_grant() -> None:
    d = PolicyEngine().decide(_proposal(), _CONTRACT, None)
    assert d.decision == "DENY" and d.rule == "no-grant"


def test_deny_expired_capability() -> None:
    d = decide(_proposal(), _grant(ttl_s=0.0, issued_at=0.0))
    assert d.decision == "DENY" and d.rule == "capability-expired"


def test_deny_operation_not_granted() -> None:
    d = decide(_proposal(operation="file.delete"), _grant())
    assert d.decision == "DENY" and d.rule == "operation-not-granted"


def test_deny_path_out_of_scope() -> None:
    d = decide(_proposal(arguments={"path": "/etc/passwd"}), _grant())
    assert d.decision == "DENY" and d.rule == "path-out-of-scope"


def test_deny_path_traversal() -> None:
    d = decide(_proposal(arguments={"path": "/ws/../secret.py"}), _grant())
    assert d.decision == "DENY" and d.rule == "path-out-of-scope"


def test_deny_tainted_side_effect() -> None:
    d = decide(_proposal(trust="retrieved_web", taint_sources=["http://x"]), _grant())
    assert d.decision == "DENY" and d.rule == "tainted-side-effect"


def test_tainted_read_is_allowed() -> None:
    d = decide(
        _proposal(operation="file.read", trust="retrieved_web"),
        _grant(operations=["file.read"]),
    )
    assert d.decision == "ALLOW"


def test_deny_egress_not_in_allowlist() -> None:
    p = _proposal(operation="net.fetch", arguments={"url": "https://evil.com/x"})
    d = decide(p, _grant(operations=["net.fetch"], network_allowlist=["pypi.org"]))
    assert d.decision == "DENY" and d.rule == "egress-not-allowed"


def test_allow_egress_in_allowlist() -> None:
    p = _proposal(operation="net.fetch", arguments={"url": "https://files.pypi.org/x"})
    d = decide(p, _grant(operations=["net.fetch"], network_allowlist=["pypi.org"]))
    assert d.decision == "ALLOW"


def test_require_approval_on_risk_class_path() -> None:
    d = decide(_proposal(arguments={"path": "/ws/auth/session.py"}), _grant())
    assert d.decision == "REQUIRE_APPROVAL" and d.rule == "risk-class-approval"


def test_risk_class_only_applies_to_side_effecting_ops() -> None:
    d = decide(
        _proposal(operation="file.read", arguments={"path": "/ws/auth/session.py"}),
        _grant(operations=["file.read"]),
    )
    assert d.decision == "ALLOW"


def test_rule_order_capability_before_path() -> None:
    # expired grant AND out-of-scope path: expiry rule wins (runs first)
    d = decide(
        _proposal(arguments={"path": "/etc/passwd"}),
        _grant(ttl_s=0.0, issued_at=0.0),
    )
    assert d.rule == "capability-expired"
