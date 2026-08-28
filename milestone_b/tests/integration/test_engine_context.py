"""Acceptance (Integration): an engine project injects an EXPERT MODE block into
the planning context and logs an ENGINE event (MILESTONE_N_PLAN.md §6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.services.engines.registry import EngineRegistry
from tests.integration.conftest import build_orchestrator, interpreter_reply, planner_reply


def _git(d: Path, *a: str) -> None:
    subprocess.run(["git", "-C", str(d), "-c", "user.email=x@x", "-c", "user.name=x", *a],
                   check=True, capture_output=True)


@pytest.fixture
def godot_repo(tmp_path: Path) -> str:
    d = tmp_path / "game"
    d.mkdir()
    (d / "project.godot").write_text(
        'config_version=5\n[application]\nconfig/features=PackedStringArray("4.2")\n', encoding="utf-8", newline="\n")
    (d / "player.gd").write_text(
        "extends Node\n\n\ndef _ready():\n    pass\n", encoding="utf-8", newline="\n")
    (d / "main.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8", newline="\n")
    (d / "test_player.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8", newline="\n")
    _git(d, "init", "-q")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "game")
    return str(d)


def test_godot_project_gets_expert_mode_and_engine_event(godot_repo: str) -> None:
    log = EventLog()
    captured: dict[str, str] = {}

    def planner_llm(system: str, prompt: str) -> str:
        captured["prompt"] = prompt
        return planner_reply(intent="add a jump", capability="fs.write")

    from app.llm.fake import ScriptedLLM as SL
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
        Interpreter(SL([interpreter_reply(
            objective="add a jump to player.gd",
            required_evidence=["T0: pytest test_player.py::test_ok passes"])])),
        Planner(SL(planner_llm)),
        ScriptedBuilder({"player.gd": "extends Node\n\n\ndef _ready():\n    pass\n\n\ndef jump():\n    pass\n"}),
        VerifierT0(runner=runner), PolicyEngine(), runner=runner,
    )
    orch.engines = EngineRegistry()

    r = orch.run("add a jump ability to the player", godot_repo)
    assert r.state == "COMPLETED"

    eng = [e for e in log.read(r.task_id) if e.kind == EventKind.ENGINE]
    assert eng and eng[0].payload["engine"] == "godot"
    assert "run-tests" in eng[0].payload["test_cmd"]
    assert "EXPERT MODE" in captured["prompt"] and "signals over" in captured["prompt"].lower() \
        or "signals and await" in captured["prompt"].lower()
    log.close()


def test_plain_python_repo_has_no_expert_block(sample_repo: str) -> None:
    log = EventLog()
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": "def add(a, b):\n    return a + b\n"},
    )
    orch.engines = EngineRegistry()
    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"
    # generic (confidence 0.05) is below the auto-enable threshold -> no ENGINE event
    assert not [e for e in log.read(r.task_id) if e.kind == EventKind.ENGINE]
    log.close()
