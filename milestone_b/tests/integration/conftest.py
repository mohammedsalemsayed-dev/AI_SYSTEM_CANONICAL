"""Helpers to build a fully-wired Orchestrator over scripted providers."""

from __future__ import annotations

import json

from app.events.log import EventLog
from app.llm.fake import ScriptedLLM
from app.orchestration.orchestrator import Orchestrator
from app.services.build.fake import ScriptedBuilder
from app.services.interpret.interpreter import Interpreter
from app.services.plan.planner import Planner
from app.services.policy.stub import AllowAllPolicy
from app.services.verify.verifier_t0 import VerifierT0


def interpreter_reply(
    *,
    objective: str = "make calc.add return a + b",
    task_class: str = "code_edit_local",
    success_criteria: list[str] | None = None,
    required_evidence: list[str] | None = None,
    ambiguity: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "objective": objective,
            "task_class": task_class,
            "success_criteria": success_criteria or ["add(2, 3) == 5"],
            "required_evidence": required_evidence
            or ["T0: pytest test_calc.py::test_add passes"],
            "assumptions": [],
            "ambiguity": ambiguity or [],
            "constraints": [],
            "risk_level": "low",
        }
    )


def planner_reply(
    intent: str = "fix add() to return a + b",
    capability: str = "fs.write",
) -> str:
    return json.dumps(
        {
            "steps": [
                {
                    "intent": intent,
                    "expected_artifact_delta": "edit calc.py",
                    "required_capability": capability,
                }
            ]
        }
    )


def build_orchestrator(
    log: EventLog,
    llm_replies: list[str],
    builder_edits,
) -> Orchestrator:
    llm = ScriptedLLM(llm_replies)
    return Orchestrator(
        log,
        Interpreter(llm),
        Planner(llm),
        ScriptedBuilder(builder_edits),
        VerifierT0(),
        AllowAllPolicy(),
    )
