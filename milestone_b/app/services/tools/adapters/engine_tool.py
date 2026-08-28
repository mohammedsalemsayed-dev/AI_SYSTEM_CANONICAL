"""Engine tool adapter — read-only detect / info (MILESTONE_S_PLAN.md §2)."""

from __future__ import annotations

from app.services.engines.registry import EngineRegistry
from app.services.tools.base import DispatchContext, ToolManifest, ToolOp, ToolResult


class EngineToolAdapter:
    name = "engine"

    def __init__(self, registry: EngineRegistry | None = None) -> None:
        self._reg = registry or EngineRegistry()

    def manifest(self) -> ToolManifest:
        r = "vcs.read"  # read-only project inspection
        return ToolManifest(
            name="engine", summary="detect the game/app engine and read its project info",
            ops=[
                ToolOp("engine.detect", "detected engine + confidence", r, '{"path"?: str}'),
                ToolOp("engine.info", "engine project info (globs, build/test cmd)", r,
                       '{"path"?: str}'),
            ],
        )

    def invoke(self, op: str, args: dict, ctx: DispatchContext) -> ToolResult:
        root = str(args.get("path") or ctx.workspace)
        adapter, info = self._reg.detect(root)
        if op == "engine.detect":
            return ToolResult(True, op, {"engine": adapter.name, "confidence": info.confidence})
        if op == "engine.info":
            return ToolResult(True, op, info.model_dump())
        return ToolResult(False, op, error=f"unknown op {op!r}")
