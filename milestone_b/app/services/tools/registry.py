"""Tool registry (MILESTONE_S_PLAN.md §2)."""

from __future__ import annotations

from app.services.tools.base import ToolAdapter, ToolOp

MANIFEST_OP_CAP = 40


class ToolRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, ToolAdapter] = {}

    def register(self, adapter: ToolAdapter) -> "ToolRegistry":
        self._by_name[adapter.name] = adapter
        return self

    def get(self, name: str) -> ToolAdapter | None:
        return self._by_name.get(name)

    def all(self) -> list[ToolAdapter]:
        return list(self._by_name.values())

    def find(self, qualified_op: str) -> tuple[ToolAdapter, ToolOp] | None:
        adapter = self._by_name.get(qualified_op.split(".", 1)[0])
        if adapter is None:
            return None
        for op in adapter.manifest().ops:
            if op.op == qualified_op:
                return adapter, op
        return None

    def manifest_block(self) -> str:
        lines = ["TOOLS — available operations (name — summary [capability]):"]
        n = 0
        for adapter in self._by_name.values():
            for op in adapter.manifest().ops:
                mark = " (side-effecting)" if op.side_effecting else ""
                lines.append(f"- {op.op} — {op.summary} [{op.capability}]{mark}")
                n += 1
                if n >= MANIFEST_OP_CAP:
                    return "\n".join(lines) + "\n"
        return "\n".join(lines) + "\n"
