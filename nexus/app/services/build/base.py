"""The `Builder` seam. Executes one plan step inside a workspace copy and returns
what changed. Concrete builders: `ScriptedBuilder` (default, offline) and
`AgentSDKBuilder` (drives the Claude Agent SDK)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.schemas.contracts import PlanStep, TaskContract


@dataclass
class BuildOutput:
    changed_paths: list[str] = field(default_factory=list)
    diff: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    error: str | None = None


@runtime_checkable
class Builder(Protocol):
    name: str

    def execute(
        self, *, task_id: str, step: PlanStep, contract: TaskContract, workspace: str
    ) -> BuildOutput: ...
