"""Frozen guardrail suite (MILESTONE_I_PLAN.md §2, design-notes §8).

A stable set of canonical tasks with known T0 oracles, run the same way every
time. `GuardrailSuite.run(run_one)` takes an injected callable — a real
orchestrator run in production, a fake in tests — so the suite mechanics are
testable offline. A promotion whose guardrail aggregate regresses does not ship
(see `regression.py`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.schemas.contracts import SuiteResult

_FIXTURE = Path(__file__).parent / "fixtures" / "guardrail_suite.json"


@dataclass(frozen=True)
class GuardrailTask:
    id: str
    task_class: str
    tags: tuple[str, ...]
    module: str
    bug: str
    fix: str
    test: str

    def request(self) -> str:
        return (
            f"A test in {self._test_name()} is failing against {self.module}. "
            f"Fix {self.module} so the test passes. The failing test is {self._test_name()}."
        )

    def _test_name(self) -> str:
        return f"test_{self.id.replace('-', '_')}.py"


class GuardrailSuite:
    def __init__(self, tasks: list[GuardrailTask] | None = None) -> None:
        self.tasks = tasks if tasks is not None else load_suite()

    def ids(self) -> list[str]:
        return [t.id for t in self.tasks]

    def run(self, run_one: Callable[[GuardrailTask], bool]) -> SuiteResult:
        """`run_one(task) -> True` iff the task's T0 oracle passes after the run.
        Tasks run in fixture order; the result is deterministic given `run_one`."""
        failures: list[str] = []
        passed = 0
        for task in self.tasks:
            ok = False
            try:
                ok = bool(run_one(task))
            except Exception:  # noqa: BLE001 — a crashing run is a failed guardrail task
                ok = False
            if ok:
                passed += 1
            else:
                failures.append(task.id)
        return SuiteResult(n=len(self.tasks), passed=passed, failures=failures)


def load_suite(path: str | Path = _FIXTURE) -> list[GuardrailTask]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        GuardrailTask(
            id=t["id"], task_class=t["task_class"], tags=tuple(t.get("tags", [])),
            module=t["module"], bug=t["bug"], fix=t["fix"], test=t["test"],
        )
        for t in raw["tasks"]
    ]


def materialize(task: GuardrailTask, root: str | Path) -> str:
    """Write the shipped-broken module + its T0 test into `root`. Returns the
    path. Used by the standalone runner and by integration tests."""
    d = Path(root)
    d.mkdir(parents=True, exist_ok=True)
    (d / task.module).write_text(task.bug, encoding="utf-8", newline="\n")
    (d / task._test_name()).write_text(task.test, encoding="utf-8", newline="\n")
    return str(d)
