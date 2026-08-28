"""Creative / Brainstorming agent (the one roster entry with no prior impl).

One LLM call before planning: given the Task Contract + file listing, produce a
few *distinct* candidate approaches. The orchestrator prepends them to the
listing the Planner sees, so the plan is chosen from real alternatives rather
than the first idea.

Advisory and fail-open: any error / malformed reply -> `[]` (the Planner just
proceeds as before). It never blocks a task and never changes the objective.
"""

from __future__ import annotations

from app.llm.base import LLM
from app.llm.parse import parse_json_object
from app.schemas.contracts import ModelRunRecord, TaskContract

BRAINSTORM_SYSTEM = """You are the Creative agent in an autonomous coding system. Before a plan
is made, you propose a few DISTINCT ways the objective could be achieved — different
strategies, not variations of one. Keep each to one sentence. Do not write code.

Reply with ONLY a JSON object:
  {"approaches": ["<approach 1>", "<approach 2>", "..."]}

2 to 4 approaches. If the objective admits only one sensible approach, return just that one."""

_MAX = 4


class Brainstorm:
    role = "creative"

    def __init__(self, llm: LLM) -> None:
        self.llm = llm

    def approaches(
        self, task_id: str, contract: TaskContract, listing: str = ""
    ) -> tuple[list[str], ModelRunRecord]:
        prompt = (
            f"OBJECTIVE\n{contract.objective}\n\n"
            f"TASK CLASS: {contract.task_class}\n"
            f"SUCCESS CRITERIA: {'; '.join(contract.success_criteria) or '(none)'}\n"
        )
        if listing:
            prompt += "\nWORKSPACE FILES:\n" + listing[:4000]
        run = ModelRunRecord(
            task_id=task_id, role="creative", model=getattr(self.llm, "model", "?"),
            provider=getattr(self.llm, "provider", "?"),
        )
        try:
            resp = self.llm.complete(system=BRAINSTORM_SYSTEM, prompt=prompt)
            run.input_tokens = getattr(resp, "input_tokens", 0)
            run.output_tokens = getattr(resp, "output_tokens", 0)
            run.latency_s = getattr(resp, "latency_s", 0.0)
            data = parse_json_object(resp.text)
            got = data.get("approaches", [])
            out = [str(a).strip() for a in got if str(a).strip()][:_MAX]
        except Exception as exc:  # noqa: BLE001 — advisory: never raise
            run.failure_mode = repr(exc)[:200]
            out = []
        return out, run
