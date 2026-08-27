"""Planner. One LLM call: Task Contract (+ file listing) -> ordered `Plan`.

Slice scope: prefer a single step for a small local change. Each step must carry a
`required_capability` token and an `expected_artifact_delta` (the EXECUTING gate,
DESIGN_TIGHTENING.md section 1).
"""

from __future__ import annotations

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.schemas.contracts import ModelRunRecord, Plan, PlanStep, TaskContract

PLANNER_SYSTEM = """You are the Planner of an autonomous coding system.
Given a Task Contract and a flat file listing, produce a minimal ordered plan.

Reply with ONLY a JSON object:
  {"steps": [
     {"intent": string,
      "expected_artifact_delta": string,   // e.g. "edit src/calc.py"
      "required_capability": string}       // short token: fs.write | fs.read | shell.run
  ]}

Prefer ONE step for a small, local change. Do not include verification steps —
verification is a separate deterministic stage.
"""


class Planner:
    role = "planner"

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def plan(
        self, contract: TaskContract, workspace_listing: str = ""
    ) -> tuple[Plan, ModelRunRecord]:
        resp = self.llm.complete(
            system=PLANNER_SYSTEM, prompt=_build_prompt(contract, workspace_listing)
        )
        data = parse_json_object(resp.text)

        steps: list[PlanStep] = []
        for raw in data.get("steps", []):
            intent = str(raw.get("intent", "")).strip()
            if not intent:
                continue
            steps.append(
                PlanStep(
                    intent=intent,
                    expected_artifact_delta=str(
                        raw.get("expected_artifact_delta", "edit files")
                    ).strip()
                    or "edit files",
                    required_capability=str(
                        raw.get("required_capability", "fs.write")
                    ).strip()
                    or "fs.write",
                )
            )
        if not steps:
            steps = [
                PlanStep(
                    intent=contract.objective,
                    expected_artifact_delta="edit files",
                    required_capability="fs.write",
                )
            ]

        plan = Plan(task_id=contract.task_id, steps=steps)
        run = ModelRunRecord(
            task_id=contract.task_id,
            role=self.role,
            provider=resp.provider,
            model=resp.model,
            latency_s=resp.latency_s,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
        )
        return plan, run


def _build_prompt(contract: TaskContract, workspace_listing: str) -> str:
    parts = [
        f"OBJECTIVE:\n{contract.objective}",
        f"SUCCESS CRITERIA:\n" + "\n".join(f"- {c}" for c in contract.success_criteria),
        f"REQUIRED EVIDENCE:\n" + "\n".join(f"- {e}" for e in contract.required_evidence),
    ]
    if contract.constraints:
        parts.append("CONSTRAINTS:\n" + "\n".join(f"- {c}" for c in contract.constraints))
    if workspace_listing:
        parts.append("WORKSPACE FILES:\n" + workspace_listing)
    parts.append("Return the plan JSON now.")
    return "\n\n".join(parts)
