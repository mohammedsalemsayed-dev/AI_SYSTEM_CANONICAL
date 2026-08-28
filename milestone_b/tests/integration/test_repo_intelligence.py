"""Acceptance (Integration): repo context reaches the Planner; the post-build
impact report selects the tests a change could break and flags broad changes
(MILESTONE_J_PLAN.md §6)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.events.log import EventKind, EventLog
from app.services.repo.facade import RepoIntelligence
from tests.integration.conftest import build_orchestrator, interpreter_reply, planner_reply


def _git(d: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(d), "-c", "user.email=x@x", "-c", "user.name=x", *a],
                   check=True, capture_output=True)


@pytest.fixture
def multi_repo(tmp_path: Path) -> str:
    d = tmp_path / "proj"
    (d / "pkg").mkdir(parents=True)
    (d / "pkg" / "__init__.py").write_text("", newline="\n")
    # core has the bug; two other modules + two test files depend on it
    (d / "pkg" / "core.py").write_text("def total(xs):\n    return sum(xs) - 1\n", newline="\n")
    (d / "pkg" / "report.py").write_text("from pkg.core import total\n\ndef line(xs):\n    return f'total={total(xs)}'\n", newline="\n")
    (d / "pkg" / "cli.py").write_text("from pkg.report import line\n", newline="\n")
    (d / "test_core.py").write_text(
        "from pkg.core import total\n\n\ndef test_total():\n    assert total([1, 2, 3]) == 6\n", newline="\n")
    (d / "test_report.py").write_text(
        "from pkg.report import line\n\n\ndef test_line():\n    assert line([1, 2, 3]) == 'total=6'\n", newline="\n")
    _git(d, "init", "-q")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "buggy")
    return str(d)


_FIXED_CORE = "def total(xs):\n    return sum(xs)\n"


def test_repo_context_reaches_planner_and_logs_event(multi_repo: str) -> None:
    log = EventLog()
    captured: dict[str, str] = {}

    def planner_llm(system: str, prompt: str) -> str:
        captured["planner_prompt"] = prompt
        return planner_reply(intent="fix total() to drop the - 1")

    from app.llm.fake import ScriptedLLM
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.sandbox.subprocess_backend import SubprocessSandbox
    from app.services.verify.verifier_t0 import VerifierT0

    runner = SubprocessSandbox()
    orch = Orchestrator(
        log,
        Interpreter(ScriptedLLM([interpreter_reply(
            objective="fix pkg.core.total",
            required_evidence=["T0: pytest test_core.py::test_total passes"])])),
        Planner(ScriptedLLM(planner_llm)),
        ScriptedBuilder({"pkg/core.py": _FIXED_CORE}),
        VerifierT0(runner=runner), PolicyEngine(), runner=runner,
    )
    orch.repo = RepoIntelligence(multi_repo)

    r = orch.run("the total function in pkg/core is off by one", multi_repo)
    assert r.state == "COMPLETED"

    repo_events = [e for e in log.read(r.task_id) if e.kind == EventKind.REPO]
    assert repo_events and repo_events[0].payload["modules"] >= 4
    assert "REPO CONTEXT" in captured["planner_prompt"]
    assert "pkg.core" in captured["planner_prompt"]
    log.close()


def test_impact_runs_the_dependent_tests(multi_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[
            interpreter_reply(objective="fix pkg.core.total",
                              required_evidence=["T0: pytest test_core.py::test_total passes"]),
            planner_reply(intent="fix total()"),
        ],
        builder_edits={"pkg/core.py": _FIXED_CORE},
    )
    orch.repo = RepoIntelligence(multi_repo)

    r = orch.run("fix the off-by-one in pkg/core.total", multi_repo)
    assert r.state == "COMPLETED"

    impact = [e for e in log.read(r.task_id) if e.kind == EventKind.IMPACT]
    assert impact
    payload = impact[0].payload
    assert "pkg.core" in payload["changed_modules"]
    assert {"pkg.report", "pkg.cli"} <= set(payload["dependent_modules"])
    assert "test_report.py" in payload["tests_affected"]

    verif = [e for e in log.read(r.task_id) if e.kind == EventKind.VERIFICATION][0]
    # T0 ran the named target AND the dependent test
    assert "test_report.py" in " ".join(verif.payload["discriminating_tests_run"])


def test_broad_change_is_flagged(multi_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[
            interpreter_reply(objective="fix pkg.core.total",
                              required_evidence=["T0: pytest test_core.py::test_total passes"]),
            planner_reply(intent="fix total()"),
        ],
        builder_edits={"pkg/core.py": "def total(xs):\n+bad\n"},  # will fail to apply/verify
    )
    orch.repo = RepoIntelligence(multi_repo)
    orch.run("touch pkg/core.total", multi_repo)

    # even on a failing run, the impact + breadth advisory is emitted
    msgs = [e for e in log.read(orch.log.task_ids()[0]) if e.kind == EventKind.AGENT_MESSAGE
            and e.payload.get("sender") == "repo"]
    assert msgs
    claims = " ".join(msgs[0].payload["claims"])
    assert "breadth" in claims
    log.close()


def test_repo_unset_is_a_no_op(multi_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[
            interpreter_reply(objective="fix pkg.core.total",
                              required_evidence=["T0: pytest test_core.py::test_total passes"]),
            planner_reply(intent="fix total()"),
        ],
        builder_edits={"pkg/core.py": _FIXED_CORE},
    )
    r = orch.run("fix it", multi_repo)
    assert r.state == "COMPLETED"
    assert not [e for e in log.read(r.task_id) if e.kind in (EventKind.REPO, EventKind.IMPACT)]
    log.close()
