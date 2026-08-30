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
def android_repo(tmp_path: Path) -> str:
    d = tmp_path / "app-proj"
    d.mkdir()
    (d / "settings.gradle").write_text("include(':app')\n", encoding="utf-8", newline="\n")
    src = d / "app" / "src" / "main"
    src.mkdir(parents=True)
    (src / "AndroidManifest.xml").write_text("<manifest/>", encoding="utf-8", newline="\n")
    (d / "app" / "build.gradle").write_text(
        "android { compileSdk 34 }\napply plugin: 'com.android.application'\n",
        encoding="utf-8", newline="\n")
    (d / "test_thing.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8", newline="\n")
    _git(d, "init", "-q")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "app")
    return str(d)


def test_engine_project_gets_expert_mode_and_engine_event(android_repo: str) -> None:
    log = EventLog()
    captured: dict[str, str] = {}

    def planner_llm(system: str, prompt: str) -> str:
        captured["prompt"] = prompt
        return planner_reply(intent="fix it", capability="fs.write")

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
            objective="fix the thing",
            required_evidence=["T0: pytest test_thing.py::test_ok passes"])])),
        Planner(SL(planner_llm)),
        ScriptedBuilder({"note.txt": "touched\n"}),
        VerifierT0(runner=runner), PolicyEngine(), runner=runner,
    )
    orch.engines = EngineRegistry()

    r = orch.run("fix the thing", android_repo)
    assert r.state == "COMPLETED"

    eng = [e for e in log.read(r.task_id) if e.kind == EventKind.ENGINE]
    assert eng and eng[0].payload["engine"] == "android"
    assert "gradlew" in eng[0].payload["test_cmd"]
    assert "EXPERT MODE" in captured["prompt"] and "viewmodel" in captured["prompt"].lower()
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
