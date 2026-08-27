"""Offline end-to-end demo — no API key needed.

    python -m app.cli.demo

Builds a throwaway git repo with a failing test, runs the full slice with a
scripted LLM + scripted Builder, and prints the event timeline and result.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from app.cli.run_task import print_timeline
from app.events.log import EventLog
from app.llm.fake import ScriptedLLM
from app.orchestration.orchestrator import Orchestrator
from app.services.build.fake import ScriptedBuilder
from app.services.interpret.interpreter import Interpreter
from app.services.plan.planner import Planner
from app.services.policy.engine import PolicyEngine
from app.services.verify.verifier_t0 import VerifierT0

_BUGGY = "def add(a, b):\n    return a - b\n"
_FIXED = "def add(a, b):\n    return a + b\n"
_TEST = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"


def _make_repo() -> str:
    repo = Path(tempfile.mkdtemp(prefix="slice_demo_"))
    (repo / "calc.py").write_text(_BUGGY, encoding="utf-8", newline="\n")
    (repo / "test_calc.py").write_text(_TEST, encoding="utf-8", newline="\n")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "buggy"]):
        subprocess.run(
            ["git", "-c", "user.email=demo@local", "-c", "user.name=demo", *args],
            cwd=repo,
            check=True,
            capture_output=True,
        )
    return str(repo)


def main() -> int:
    repo = _make_repo()
    interp = json.dumps(
        {
            "objective": "make calc.add return a + b",
            "task_class": "code_edit_local",
            "success_criteria": ["add(2, 3) == 5"],
            "required_evidence": ["T0: pytest test_calc.py::test_add passes"],
            "assumptions": [],
            "ambiguity": [],
            "constraints": [],
            "risk_level": "low",
        }
    )
    plan = json.dumps(
        {
            "steps": [
                {
                    "intent": "fix add() to return a + b",
                    "expected_artifact_delta": "edit calc.py",
                    "required_capability": "fs.write",
                }
            ]
        }
    )
    llm = ScriptedLLM([interp, plan])
    log = EventLog()
    orch = Orchestrator(
        log,
        Interpreter(llm),
        Planner(llm),
        ScriptedBuilder({"calc.py": _FIXED}),
        VerifierT0(),
        PolicyEngine(),
    )
    result = orch.run("the add function is wrong, fix it", repo)
    print_timeline(log, result.task_id)
    print("\n=== result ===")
    print(result.model_dump_json(indent=2))
    log.close()
    return 0 if result.state == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
