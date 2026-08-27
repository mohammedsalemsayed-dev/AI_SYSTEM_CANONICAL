"""Acceptance (Integration): multi-step execution with progress tracking, and a
looping builder caught by the loop detector -> escalation ladder -> WAITING_FOR_USER
(MILESTONE_D_PLAN.md §6)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.events.log import EventKind, EventLog
from app.events.projections import project_task
from tests.integration.conftest import build_orchestrator, interpreter_reply


def _plan(*intents: str) -> str:
    return json.dumps(
        {
            "steps": [
                {
                    "intent": it,
                    "expected_artifact_delta": "edit a file",
                    "required_capability": "fs.write",
                }
                for it in intents
            ]
        }
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=x@x", "-c", "user.name=x", *args],
        cwd=cwd, check=True, capture_output=True,
    )


@pytest.fixture
def two_file_repo(tmp_path: Path) -> str:
    repo = tmp_path / "twofile"
    repo.mkdir()
    (repo / "mod_a.py").write_text("def a():\n    return 1\n", encoding="utf-8", newline="\n")
    (repo / "mod_b.py").write_text("def b():\n    return 10\n", encoding="utf-8", newline="\n")
    (repo / "test_both.py").write_text(
        "from mod_a import a\nfrom mod_b import b\n\n\n"
        "def test_sum():\n    assert a() + b() == 22\n",
        encoding="utf-8", newline="\n",
    )
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "buggy")
    return str(repo)


def test_two_step_task_completes_with_healthy_progress(two_file_repo: str) -> None:
    calls = {"n": 0}

    def edits(ws: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            (Path(ws) / "mod_a.py").write_text("def a():\n    return 2\n", newline="\n")
        else:
            (Path(ws) / "mod_b.py").write_text("def b():\n    return 20\n", newline="\n")

    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[
            interpreter_reply(
                objective="make a()+b() == 22",
                required_evidence=["T0: pytest test_both.py::test_sum passes"],
            ),
            _plan("fix a() to return 2", "fix b() to return 20"),
        ],
        builder_edits=edits,
    )
    result = orch.run("fix a and b so they sum to 22", two_file_repo)

    assert result.state == "COMPLETED"
    assert calls["n"] == 2
    progress = [e.payload for e in log.read(result.task_id) if e.kind == EventKind.PROGRESS]
    assert len(progress) == 2
    assert all(p["effective_class"] in ("HEALTHY_PROGRESS", "SLOW_PROGRESS") for p in progress)
    assert progress[-1]["hard_progress"] is True  # the second edit makes the test pass


def test_looping_builder_is_caught_and_pauses_for_user(two_file_repo: str) -> None:
    # builder makes the same wrong edit every step -> test keeps failing the same way
    def bad_edit(ws: str) -> None:
        (Path(ws) / "mod_a.py").write_text("def a():\n    return 999\n", newline="\n")

    steps = _plan(*["retry the fix"] * 4)
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[
            interpreter_reply(
                objective="make a()+b() == 22",
                required_evidence=["T0: pytest test_both.py::test_sum passes"],
            ),
            steps,   # initial plan
            steps,   # ladder re-plan #1
            steps,   # ladder re-plan #2
        ],
        builder_edits=bad_edit,
    )
    result = orch.run("fix the sum", two_file_repo)

    assert result.state == "WAITING_FOR_USER"
    kinds = [e.kind for e in log.read(result.task_id)]
    assert EventKind.ESCALATION in kinds

    prog = [e.payload for e in log.read(result.task_id) if e.kind == EventKind.PROGRESS]
    assert any(p["effective_class"] in ("LOOP_RISK", "STALLED") for p in prog)

    rungs = [e.payload["rung"] for e in log.read(result.task_id) if e.kind == EventKind.ESCALATION]
    assert "change_strategy" in rungs
    assert rungs[-1] == "ask_user"

    snap = project_task(log.read(result.task_id))
    assert snap.state.value == "WAITING_FOR_USER"


def test_replan_recovers_a_stalled_task(two_file_repo: str) -> None:
    # first plan's builder does nothing useful; after a re-plan, the builder fixes it
    phase = {"replanned": False}

    def edits(ws: str) -> None:
        if not phase["replanned"]:
            (Path(ws) / "mod_a.py").write_text("def a():\n    return 1\n", newline="\n")  # no-op
        else:
            (Path(ws) / "mod_a.py").write_text("def a():\n    return 2\n", newline="\n")
            (Path(ws) / "mod_b.py").write_text("def b():\n    return 20\n", newline="\n")

    class Marker:
        """flip the phase flag the first time the planner is called again."""

        def __init__(self, inner):
            self.inner = inner
            self.calls = 0

        def plan(self, contract, listing=""):
            self.calls += 1
            if self.calls >= 2:
                phase["replanned"] = True
            return self.inner.plan(contract, listing)

    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[
            interpreter_reply(
                objective="make a()+b() == 22",
                required_evidence=["T0: pytest test_both.py::test_sum passes"],
            ),
            _plan(*["noop"] * 4),
            _plan("fix both modules"),
        ],
        builder_edits=edits,
    )
    orch.planner = Marker(orch.planner)
    result = orch.run("fix the sum", two_file_repo)

    assert result.state == "COMPLETED"
    rungs = [e.payload["rung"] for e in log.read(result.task_id) if e.kind == EventKind.ESCALATION]
    assert "change_strategy" in rungs
