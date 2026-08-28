"""Tool adapter contract (MILESTONE_S_PLAN.md §2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.schemas.contracts import CapabilityGrant


@dataclass
class ToolOp:
    op: str                        # qualified: "<adapter>.<verb>"
    summary: str
    capability: str                # the one capability token this op needs
    args_hint: str = ""
    output_trust: str = "workspace"  # workspace | retrieved_web | doc_input | tool_output
    side_effecting: bool = False


@dataclass
class ToolManifest:
    name: str
    summary: str
    ops: list[ToolOp] = field(default_factory=list)


@dataclass
class ToolResult:
    ok: bool
    op: str
    output: Any = None
    trust: str = "workspace"
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class DispatchContext:
    task_id: str = ""
    grant: CapabilityGrant | None = None
    workspace: str = "."
    trust: str = "workspace"          # trust of the inputs driving this call
    taint_sources: list[str] = field(default_factory=list)


@runtime_checkable
class ToolAdapter(Protocol):
    name: str

    def manifest(self) -> ToolManifest: ...

    def invoke(self, op: str, args: dict, ctx: DispatchContext) -> ToolResult: ...
