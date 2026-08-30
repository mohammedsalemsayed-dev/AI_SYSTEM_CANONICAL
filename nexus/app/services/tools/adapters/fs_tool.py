"""Filesystem tool adapter — operates on a workspace copy (MILESTONE_S_PLAN.md §2)."""

from __future__ import annotations

from pathlib import Path

from app.services.tools.base import DispatchContext, ToolManifest, ToolOp, ToolResult

READ_CAP_BYTES = 256 * 1024


class FsToolAdapter:
    name = "fs"

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="fs", summary="read / list / write files inside the task workspace",
            ops=[
                ToolOp("fs.read", "read a file as text", "fs.read", '{"path": str}'),
                ToolOp("fs.list", "list files under a subdir", "fs.read", '{"path"?: str}'),
                ToolOp("fs.write", "write a file (workspace-scoped)", "fs.write",
                       '{"path": str, "text": str}', side_effecting=True),
            ],
        )

    def _resolve(self, ctx: DispatchContext, rel: str) -> Path | None:
        root = Path(ctx.workspace).resolve()
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target

    def invoke(self, op: str, args: dict, ctx: DispatchContext) -> ToolResult:
        if op == "fs.read":
            p = self._resolve(ctx, str(args.get("path", "")))
            if p is None or not p.is_file():
                return ToolResult(False, op, error="path outside workspace or not a file")
            data = p.read_bytes()
            trunc = len(data) > READ_CAP_BYTES
            return ToolResult(True, op, data[:READ_CAP_BYTES].decode("utf-8", "replace"),
                              meta={"truncated": trunc, "bytes": len(data)})
        if op == "fs.list":
            base = self._resolve(ctx, str(args.get("path", ".")))
            if base is None or not base.is_dir():
                return ToolResult(False, op, error="path outside workspace or not a dir")
            root = Path(ctx.workspace).resolve()
            return ToolResult(True, op, sorted(
                str(f.relative_to(root)).replace("\\", "/")
                for f in base.rglob("*") if f.is_file() and ".git" not in f.parts
            ))
        if op == "fs.write":
            p = self._resolve(ctx, str(args.get("path", "")))
            if p is None:
                return ToolResult(False, op, error="path outside workspace")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(args.get("text", "")), encoding="utf-8", newline="\n")
            return ToolResult(True, op, {"written": str(p.relative_to(Path(ctx.workspace).resolve()))})
        return ToolResult(False, op, error=f"unknown op {op!r}")
