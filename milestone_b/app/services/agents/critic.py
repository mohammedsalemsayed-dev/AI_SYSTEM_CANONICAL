"""Critic role (MILESTONE_E_PLAN.md §2, DESIGN_TIGHTENING §9, §14.1).

A one-shot pass on the Builder's diff *before* verification. Fresh model context:
sees the Task Contract, the diff, and the failing test text — NOT the build
narrative. Emits a `CriticReport`. `reject` routes back to the Builder once with
the findings; `accept` / `revise` proceed to verification.

Advisory path fails open: a malformed or errored Critic response -> `accept` with
a logged warning (it must never *block* a task on its own error), but a genuine
`reject` is honoured.
"""

from __future__ import annotations

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.schemas.contracts import (
    CriticFinding,
    CriticReport,
    ModelRunRecord,
    TaskContract,
)

CRITIC_SYSTEM = """You are the Critic in an autonomous coding system. You did NOT write this
change. Judge whether the diff satisfies the Task Contract and passes the named test
*as written*.

Look for: the diff does not actually make the target test pass; it matches behaviour
but not the test's exact assertion (wrong exception type or message, off-by-one boundary);
it satisfies the test by coincidence while violating a stated success criterion; it edits
the test; it introduces an obvious regression, security, or correctness problem.

Reply with ONLY a JSON object:
  {"verdict": "accept" | "revise" | "reject",
   "summary": string,
   "findings": [{"severity": "blocking"|"major"|"minor", "claim": string}]}

"reject" = the change should not proceed to verification as-is (blocking problem).
"revise" = it will likely pass but has a major issue worth fixing.
"accept" = no blocking or major issue found.
"""


class Critic:
    role = "critic"

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def review(
        self,
        task_id: str,
        contract: TaskContract,
        diff: str,
        test_text: str,
    ) -> tuple[CriticReport, ModelRunRecord]:
        prompt = _build_prompt(contract, diff, test_text)
        try:
            resp = self.llm.complete(system=CRITIC_SYSTEM, prompt=prompt)
            data = parse_json_object(resp.text)
            verdict = data.get("verdict", "accept")
            if verdict not in ("accept", "revise", "reject"):
                verdict = "accept"
            findings = [
                CriticFinding(
                    severity=f.get("severity", "minor")
                    if f.get("severity") in ("blocking", "major", "minor")
                    else "minor",
                    claim=str(f.get("claim", "")).strip(),
                )
                for f in data.get("findings", [])
                if str(f.get("claim", "")).strip()
            ]
            report = CriticReport(
                task_id=task_id,
                verdict=verdict,
                findings=findings,
                summary=str(data.get("summary", "")).strip(),
            )
        except Exception as exc:  # advisory path fails open
            report = CriticReport(
                task_id=task_id,
                verdict="accept",
                summary=f"critic unavailable, proceeding on T0 alone: {exc!r}",
            )
            resp = None

        run = ModelRunRecord(
            task_id=task_id,
            role=self.role,
            provider=getattr(resp, "provider", "") if resp else "",
            model=getattr(resp, "model", "") if resp else "",
            latency_s=getattr(resp, "latency_s", 0.0) if resp else 0.0,
            input_tokens=getattr(resp, "input_tokens", 0) if resp else 0,
            output_tokens=getattr(resp, "output_tokens", 0) if resp else 0,
            failure_mode=None if resp else "critic_error",
        )
        return report, run


def _build_prompt(contract: TaskContract, diff: str, test_text: str) -> str:
    parts = [
        f"OBJECTIVE:\n{contract.objective}",
        "SUCCESS CRITERIA:\n" + "\n".join(f"- {c}" for c in contract.success_criteria),
        "REQUIRED EVIDENCE:\n" + "\n".join(f"- {e}" for e in contract.required_evidence),
    ]
    if contract.constraints:
        parts.append("CONSTRAINTS:\n" + "\n".join(f"- {c}" for c in contract.constraints))
    if test_text:
        parts.append("TARGET TEST (the change must make this pass as written):\n" + test_text)
    parts.append("DIFF UNDER REVIEW:\n" + (diff or "(empty)"))
    parts.append("Return the CriticReport JSON now.")
    return "\n\n".join(parts)
