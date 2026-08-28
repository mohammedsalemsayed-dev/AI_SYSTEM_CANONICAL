"""Independent model Verifier — T2 tier (DESIGN_TIGHTENING §5, MILESTONE_E_PLAN §2).

Given ONLY the Task Contract + the diff — never the build narrative — a model
independently derives pass/fail for each success criterion. Run in N independent
contexts (ensemble). Unanimous pass -> pass; any split -> `overall="fail"` plus a
`disagreement` flag for the 5-step protocol. T2 is never authoritative over the
deterministic T0; it can only *raise* a concern.
"""

from __future__ import annotations

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.schemas.contracts import (
    CriterionVerdict,
    ModelRunRecord,
    TaskContract,
    VerificationRecord,
    new_id,
)

T2_SYSTEM = """You are an independent Verifier. You did NOT write this change and you have
NOT seen how it was produced. Decide, from the Task Contract and the diff alone, whether the
change satisfies EACH success criterion.

Reply with ONLY a JSON object:
  {"criteria": [{"criterion": string, "verdict": "pass"|"fail"|"unknown", "note": string}],
   "overall": "pass"|"fail"}

"overall" is "pass" only if every criterion you can judge is "pass" and none is "fail".
Judge only what the diff shows; if you cannot tell, use "unknown" (not "fail").
"""


class VerifierT2:
    tier = "T2"

    def __init__(self, llm: LLM, contexts: int = 2) -> None:
        self.llm = llm
        self.contexts = max(1, contexts)

    def verify(
        self,
        *,
        task_id: str,
        contract: TaskContract,
        diff: str,
        original_workspace: str | None = None,
    ) -> tuple[VerificationRecord, ModelRunRecord]:
        prompt = _build_prompt(contract, diff)
        passes: list[bool] = []
        per_criterion: list[CriterionVerdict] = []
        in_tok = out_tok = 0
        note = ""

        for _ in range(self.contexts):
            try:
                resp = self.llm.complete(system=T2_SYSTEM, prompt=prompt)
                data = parse_json_object(resp.text)
                in_tok += getattr(resp, "input_tokens", 0)
                out_tok += getattr(resp, "output_tokens", 0)
                ov = data.get("overall", "fail")
                passes.append(ov == "pass")
                if not per_criterion:  # keep the first context's breakdown
                    per_criterion = [
                        CriterionVerdict(
                            criterion=str(c.get("criterion", "")),
                            verdict=c.get("verdict", "unknown")
                            if c.get("verdict") in ("pass", "fail", "unknown")
                            else "unknown",
                        )
                        for c in data.get("criteria", [])
                    ]
            except Exception as exc:  # a broken context abstains
                note = f"a T2 context errored: {exc!r}"
                passes.append(False)

        unanimous_pass = passes and all(passes)
        disagreement = len(set(passes)) > 1
        overall = "pass" if unanimous_pass else "fail"

        record = VerificationRecord(
            id=new_id("ver"),
            task_id=task_id,
            tier="T2",
            criteria=per_criterion,
            overall=overall,
            residual_uncertainty=(
                ("contexts split: " + str(passes)) if disagreement else note
            ),
        )
        run = ModelRunRecord(
            task_id=task_id,
            role="verifier_t2",
            provider="",
            model="",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
        return record, run

    @staticmethod
    def is_split(record: VerificationRecord) -> bool:
        return record.residual_uncertainty.startswith("contexts split")


def _build_prompt(contract: TaskContract, diff: str) -> str:
    return "\n\n".join(
        [
            f"OBJECTIVE:\n{contract.objective}",
            "SUCCESS CRITERIA:\n" + "\n".join(f"- {c}" for c in contract.success_criteria),
            "REQUIRED EVIDENCE:\n" + "\n".join(f"- {e}" for e in contract.required_evidence),
            "DIFF:\n" + (diff or "(empty)"),
            "Return the verification JSON now.",
        ]
    )
