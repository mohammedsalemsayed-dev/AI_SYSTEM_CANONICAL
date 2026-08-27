"""Interpreter / Intent Compiler.

One LLM call: request text (+ workspace listing) -> draft `TaskContract`.
It compiles the objective, it does not rewrite it (D14). If it cannot name a
runnable pytest T0 target, the blocking issue goes into `ambiguity` so the
orchestrator routes to WAITING_FOR_USER rather than guessing
(DESIGN_TIGHTENING.md sections 1 and 5).
"""

from __future__ import annotations

from typing import get_args

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.schemas.contracts import (
    ModelRunRecord,
    TaskClass,
    TaskContract,
    validate_contract,
)
from app.services.budget.tracker import default_budget

_VALID_CLASSES = set(get_args(TaskClass))

INTERPRETER_SYSTEM = """You are the Interpreter / Intent Compiler of an autonomous coding system.
Compile the user's request into a Task Contract. Do NOT change the objective — compile it, don't rewrite it.

Reply with ONLY a JSON object, no prose, with these keys:
  objective:          string — the concrete outcome, in your words but faithful to the request
  task_class:         one of qa_explain, code_edit_local, code_edit_broad, debug, research_web,
                      doc_analysis, authoring, planning_arch, ops
  success_criteria:   string[] — observable conditions that mean the task is done
  required_evidence:  string[] — MUST contain one entry of the exact form
                      "T0: pytest <path-or-nodeid> passes" naming a runnable test.
                      The <path-or-nodeid> MUST be relative to the repository root and
                      appear verbatim in WORKSPACE FILES (e.g. "test_age.py::test_x") —
                      do NOT prepend any directory that is not in that list.
                      If exactly one test file in WORKSPACE FILES plainly covers the
                      described behavior, use it as a whole-file target
                      (e.g. "T0: pytest test_paginate.py passes") — do NOT raise ambiguity
                      just because no specific node id was named.
                      Only if there is genuinely no test file that could cover this: give
                      your best guess here AND put the blocking question in "ambiguity".
  assumptions:        string[]
  ambiguity:          string[] — questions that materially change the result; empty if none
  constraints:        string[]
  risk_level:         "low" | "medium" | "high"
"""


class Interpreter:
    role = "interpreter"

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def compile(
        self, task_id: str, request_text: str, workspace_listing: str = ""
    ) -> tuple[TaskContract, ModelRunRecord]:
        prompt = _build_prompt(request_text, workspace_listing)
        resp = self.llm.complete(system=INTERPRETER_SYSTEM, prompt=prompt)
        data = parse_json_object(resp.text)

        task_class = data.get("task_class", "code_edit_local")
        if task_class not in _VALID_CLASSES:
            task_class = "code_edit_local"

        contract = TaskContract(
            task_id=task_id,
            original_request=request_text,
            objective=str(data.get("objective", "")).strip(),
            task_class=task_class,
            success_criteria=[str(x) for x in data.get("success_criteria", [])],
            required_evidence=[str(x) for x in data.get("required_evidence", [])],
            assumptions=[str(x) for x in data.get("assumptions", [])],
            ambiguity=[str(x) for x in data.get("ambiguity", [])],
            constraints=[str(x) for x in data.get("constraints", [])],
            risk_level=data.get("risk_level", "low")
            if data.get("risk_level") in {"low", "medium", "high"}
            else "low",
            budget=default_budget(task_class),
        )

        # A contract that fails the INTERPRETING gate but was not flagged by the
        # model is still a reason to ask the user — surface it as ambiguity.
        problems = validate_contract(contract)
        if problems and not contract.ambiguity:
            contract.ambiguity = [f"cannot verify this task — {p}" for p in problems]

        run = ModelRunRecord(
            task_id=task_id,
            role=self.role,
            provider=resp.provider,
            model=resp.model,
            latency_s=resp.latency_s,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )
        return contract, run


def _build_prompt(request_text: str, workspace_listing: str) -> str:
    parts = [f"USER REQUEST:\n{request_text}"]
    if workspace_listing:
        parts.append(
            "WORKSPACE FILES (flat list; pick real test paths from here):\n"
            + workspace_listing
        )
    parts.append("Return the Task Contract JSON now.")
    return "\n\n".join(parts)
