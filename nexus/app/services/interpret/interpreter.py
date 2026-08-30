"""Interpreter / Intent Compiler.

One LLM call: request text (+ workspace listing) -> draft `TaskContract`.
It compiles the objective, it does not rewrite it (D14). If it cannot name a
runnable pytest T0 target, the blocking issue goes into `ambiguity` so the
orchestrator routes to WAITING_FOR_USER rather than guessing
(design-notes sections 1 and 5).
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
# classes that answer rather than change files — no T0 pytest target required
_NO_T0_CLASSES = {"qa_explain", "research_web", "doc_analysis", "planning_arch", "authoring"}

# deterministic guard: a small local Interpreter sometimes tags a plain question
# as a code-edit. If the text reads as a pure question with no change verb, force
# qa_explain — but only when the model picked a code-edit / debug class.
import re as _re

_QUESTION_RE = _re.compile(
    r"^\s*(what|why|how|when|where|which|who|does|do|did|is|are|was|were|can|could|"
    r"should|would|will|explain|describe|tell me|summarise|summarize)\b",
    _re.IGNORECASE,
)
_CHANGE_VERB_RE = _re.compile(
    r"\b(fix|add|create|make|write|build|implement|change|update|refactor|rename|"
    r"delete|remove|replace|generate|draft|convert|migrate|install|wire)\b",
    _re.IGNORECASE,
)
_QA_OVERRIDABLE = {"code_edit_local", "code_edit_broad", "debug", "ops"}

# "make/write/export a <deck|word doc|report|pdf|brief|...>" is an authoring
# deliverable, not a code edit — the model sometimes files it as code_edit_broad
# (esp. a follow-up like "now also export a PDF brief"). Deterministic nudge.
_AUTHORING_RE = _re.compile(
    r"\b(make|create|write|draft|generate|export|produce|prepare|put together|build)\b"
    r"[^.]{0,50}?\b(slide\s?deck|slides?|deck|presentation|power\s?point|pptx|keynote|"
    r"word\s+(?:doc|document|report|file)|docx|\breport\b|pdf|brief|white\s?paper|memo|"
    r"essay|proposal|one[-\s]?pager|hand\s?out)\b",
    _re.IGNORECASE,
)
# ...unless it's clearly about writing CODE that produces such a thing
_AUTHORING_CODE_GUARD = _re.compile(
    r"\b(function|classes?|scripts?|module|codebase|api|endpoint|library|package|"
    r"unit\s?test|parser|renderer|generator\s+class)\b",
    _re.IGNORECASE,
)
_AUTHORING_OVERRIDABLE = {"code_edit_local", "code_edit_broad", "debug", "ops"}


def _looks_like_question(text: str) -> bool:
    t = (text or "").strip()
    return bool(_QUESTION_RE.match(t)) and not _CHANGE_VERB_RE.search(t)


def _looks_like_authoring(text: str) -> bool:
    t = (text or "")
    return bool(_AUTHORING_RE.search(t)) and not _AUTHORING_CODE_GUARD.search(t)

INTERPRETER_SYSTEM = """You are the Interpreter / Intent Compiler of an autonomous coding system.
Compile the user's request into a Task Contract. Do NOT change the objective — compile it, don't rewrite it.

Reply with ONLY a JSON object, no prose, with these keys:
  objective:          string — the concrete outcome, in your words but faithful to the request
  task_class:         one of qa_explain, code_edit_local, code_edit_broad, debug, research_web,
                      doc_analysis, authoring, planning_arch, ops
                      Use qa_explain when the request only asks you to explain, describe,
                      summarise or answer — nothing in the workspace should change — EVEN IF
                      it refers to earlier actions or says "and retry"/"and fix it". A request
                      that changes files is code_edit_* or debug; a pure question is qa_explain.
                      Use authoring when the deliverable is a DOCUMENT or PRESENTATION —
                      "write a report", "make a Word doc", "create a PowerPoint / slide deck /
                      presentation about X", "draft a proposal". Not code.
  success_criteria:   string[] — observable conditions that mean the task is done
  required_evidence:  string[] — for code_edit_local / code_edit_broad / debug this MUST contain
                      one entry of the exact form
                      "T0: pytest <path-or-nodeid> passes" naming a runnable test.
                      For qa_explain / research_web / doc_analysis / planning_arch a T0 pytest
                      entry is NOT required — give a one-line description of how a good answer
                      would be judged instead.
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
        # deterministic override: a plain question should never go down the build path
        if task_class in _QA_OVERRIDABLE and _looks_like_question(request_text):
            task_class = "qa_explain"
        # deterministic override: "make/export a deck / word doc / pdf / report"
        # is an authoring deliverable, not a code edit
        elif (task_class in _AUTHORING_OVERRIDABLE
              and _looks_like_authoring(request_text)
              and not _looks_like_question(request_text)):
            task_class = "authoring"

        success = [str(x) for x in data.get("success_criteria", [])]
        evidence = [str(x) for x in data.get("required_evidence", [])]
        assumptions = [str(x) for x in data.get("assumptions", [])]
        ambiguity = [str(x) for x in data.get("ambiguity", [])]
        # a pure-answer class needs no runnable test target and is never *blocked*
        # by ambiguity — it answers with a stated assumption instead of stalling
        # in WAITING_FOR_USER (and the INTERPRETING->PLANNING gate rejects a
        # contract with open ambiguity, which would hard-fail the fast path).
        if task_class in _NO_T0_CLASSES:
            if not success:
                success = ["the answer addresses the question using available context"]
            if not evidence:
                evidence = ["a clear, correct answer grounded in the workspace / session context"]
            if ambiguity:
                assumptions += [f"open point (answered with best judgement): {a}" for a in ambiguity]
                ambiguity = []

        contract = TaskContract(
            task_id=task_id,
            original_request=request_text,
            objective=str(data.get("objective", "")).strip(),
            task_class=task_class,
            success_criteria=success,
            required_evidence=evidence,
            assumptions=assumptions,
            ambiguity=ambiguity,
            constraints=[str(x) for x in data.get("constraints", [])],
            risk_level=data.get("risk_level", "low")
            if data.get("risk_level") in {"low", "medium", "high"}
            else "low",
            budget=default_budget(task_class),
        )

        # A contract that fails the INTERPRETING gate but was not flagged by the
        # model is still a reason to ask the user — surface it as ambiguity.
        # (answer-type classes are exempt: they don't take the plan/verify path.)
        problems = validate_contract(contract)
        if problems and not contract.ambiguity and task_class not in _NO_T0_CLASSES:
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
