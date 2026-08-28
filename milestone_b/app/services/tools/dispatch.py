"""Tool dispatcher (MILESTONE_S_PLAN.md §2, §5-C).

Turns a tool op into an `ActionProposal`, runs it past the **existing** Policy
Engine + capability grant, invokes the adapter, and stamps the result with the
manifest trust. A denial is a `PolicyDecision`, never an exception.
"""

from __future__ import annotations

from app.schemas.contracts import ActionProposal, PolicyDecision, TaskContract, new_id
from app.services.capability.registry import primary_operation
from app.services.tools.base import DispatchContext, ToolResult
from app.services.tools.registry import ToolRegistry

_MIN_CONTRACT = TaskContract(
    task_id="_tool", original_request="tool dispatch", objective="tool dispatch",
    task_class="ops", success_criteria=["op runs"], required_evidence=["tool result"],
)


class ToolDispatcher:
    def __init__(self, registry: ToolRegistry, policy, *, risk_globs: list[str] | None = None) -> None:
        self.registry = registry
        self.policy = policy
        self.risk_globs = risk_globs

    def run(self, qualified_op: str, args: dict, ctx: DispatchContext) -> tuple[ToolResult, PolicyDecision | None]:
        found = self.registry.find(qualified_op)
        if found is None:
            return ToolResult(ok=False, op=qualified_op, error="unknown tool op"), None
        adapter, op = found

        proposal = ActionProposal(
            task_id=ctx.task_id, step_id="tool",
            operation=primary_operation(op.capability),
            arguments=dict(args),
            required_capability=op.capability,
            workspace_scope=(ctx.grant.scope_path if ctx.grant else ctx.workspace),
            expected_effect=op.summary,
            idempotency_key=new_id("idem"),
            trust=ctx.trust,
            taint_sources=list(ctx.taint_sources),
        )
        decision = self.policy.decide(proposal, _MIN_CONTRACT, ctx.grant)
        if decision.decision != "ALLOW":
            return (
                ToolResult(ok=False, op=qualified_op,
                           error=f"policy {decision.decision} [{decision.rule}]: {decision.reason}"),
                decision,
            )

        try:
            result = adapter.invoke(qualified_op, args, ctx)
        except Exception as exc:  # noqa: BLE001 — an adapter failure is a result, not a raise
            return ToolResult(ok=False, op=qualified_op, error=repr(exc)), decision

        result.op = qualified_op
        result.trust = op.output_trust
        return result, decision
