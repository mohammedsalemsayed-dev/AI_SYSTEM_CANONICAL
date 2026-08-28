"""Shell tool adapter — one sandboxed `shell.exec` op (MILESTONE_T_PLAN.md §2).

Delegates to the existing `SandboxRunner` seam. The fallback backend is **not**
isolation (see `subprocess_backend.py`); `shell.run` is a distinct capability
token precisely so a grant must name it explicitly.
"""

from __future__ import annotations

from app.services.sandbox.runner import (
    SandboxRefused,
    SandboxRunner,
    SandboxSpec,
    SandboxUnavailable,
)
from app.services.sandbox.subprocess_backend import SubprocessSandbox
from app.services.tools.base import DispatchContext, ToolManifest, ToolOp, ToolResult

_MAX_OUT = 8000
_MAX_TIMEOUT = 120
_DEFAULT_TIMEOUT = 30


class ShellToolAdapter:
    name = "shell"

    def __init__(self, runner: SandboxRunner | None = None) -> None:
        self._runner = runner or SubprocessSandbox()

    def manifest(self) -> ToolManifest:
        return ToolManifest(
            name="shell", summary="run a command in the task sandbox",
            ops=[
                ToolOp("shell.exec", "run an argv command in the sandbox", "shell.run",
                       '{"command": [str, ...], "timeout_s"?: int}',
                       output_trust="tool_output", side_effecting=True),
            ],
        )

    def invoke(self, op: str, args: dict, ctx: DispatchContext) -> ToolResult:
        if op != "shell.exec":
            return ToolResult(False, op, error=f"unknown op {op!r}")
        cmd = args.get("command")
        if not isinstance(cmd, (list, tuple)) or not cmd or not all(isinstance(c, str) for c in cmd):
            return ToolResult(False, op, error="command must be a non-empty list of strings")
        try:
            timeout = int(args.get("timeout_s", _DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT
        spec = SandboxSpec(
            workdir=ctx.workspace,
            command=[str(c) for c in cmd],
            timeout_s=max(1, min(timeout, _MAX_TIMEOUT)),
            allow_non_isolated=True,
        )
        try:
            res = self._runner.run(spec)
        except (SandboxRefused, SandboxUnavailable, OSError, ValueError) as exc:
            return ToolResult(False, op, error=repr(exc), trust="tool_output")
        return ToolResult(
            ok=res.ok, op=op,
            output={
                "exit_code": res.exit_code,
                "stdout": res.stdout[:_MAX_OUT],
                "stderr": res.stderr[:_MAX_OUT],
                "timed_out": res.timed_out,
            },
            trust="tool_output",
            error=res.error or ("" if res.ok else f"exit {res.exit_code}"),
            meta={"backend": res.backend},
        )
