"""Deterministic `Builder` for tests and offline runs.

Constructed with either:
  - a dict `{relative_path: new_content}` applied on every step; or
  - a callable `(workspace_path) -> None` that mutates the copy; or
  - a callable that raises, to simulate a builder failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.schemas.contracts import PlanStep, TaskContract
from app.services.build.base import BuildOutput
from app.services.build.workspace_copy import diff_workspace


class ScriptedBuilder:
    name = "fake"

    def __init__(
        self, edits: dict[str, str] | Callable[[str], None]
    ) -> None:
        self._edits = edits
        self.calls: list[str] = []

    def execute(
        self, *, task_id: str, step: PlanStep, contract: TaskContract, workspace: str
    ) -> BuildOutput:
        self.calls.append(step.id)
        try:
            if callable(self._edits):
                self._edits(workspace)
            else:
                for rel, content in self._edits.items():
                    target = Path(workspace) / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8", newline="\n")
            diff, names = diff_workspace(workspace)
            return BuildOutput(
                changed_paths=names,
                diff=diff,
                stdout="scripted edit applied",
                exit_code=0,
            )
        except Exception as exc:  # simulate builder failure
            return BuildOutput(exit_code=1, error=repr(exc))
