"""Egress tool adapter — wraps `EgressBroker` (MILESTONE_S_PLAN.md §2, §14.3)."""

from __future__ import annotations

from app.services.egress.broker import EgressBroker, EgressDenied, EgressError
from app.services.tools.base import DispatchContext, ToolManifest, ToolOp, ToolResult

_MAX_TEXT = 8000


class EgressToolAdapter:
    name = "net"

    def __init__(self, broker: EgressBroker) -> None:
        self._broker = broker

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="net", summary="fetch a URL through the egress broker (default deny)",
            ops=[
                ToolOp("net.fetch", "fetch a URL (allowlist only)", "net.fetch",
                       '{"url": str}', output_trust="retrieved_web", side_effecting=True),
            ],
        )

    def invoke(self, op: str, args: dict, ctx: DispatchContext) -> ToolResult:
        if op != "net.fetch":
            return ToolResult(False, op, error=f"unknown op {op!r}")
        url = str(args.get("url", ""))
        try:
            res = self._broker.fetch(url)
        except (EgressDenied, EgressError) as exc:
            return ToolResult(False, op, error=repr(exc), trust="retrieved_web")
        text = res.content.decode("utf-8", "replace")[:_MAX_TEXT]
        return ToolResult(True, op, {"url": url, "text": text}, trust="retrieved_web",
                          meta={"status": res.status})
