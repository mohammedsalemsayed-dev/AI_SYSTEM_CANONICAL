"""Bounded, deterministic tool-use loop (MILESTONE_T_PLAN.md §2).

The model is shown the tool manifest and the transcript so far; it replies with
ONE JSON object per turn — `{"op": "...", "args": {...}}` to call a tool, or
`{"done": true, "summary": "..."}` to stop. Every call is dispatched through the
Milestone S `ToolDispatcher`, so it passes the existing §5-C Policy Engine +
capability grant. A denial is a transcript turn, never an exception.

Determinism: the loop takes no wall-clock or random input. The same scripted
replies + the same workspace produce a byte-identical transcript.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.llm.parse import parse_json_object
from app.services.tools.base import DispatchContext
from app.services.tools.dispatch import ToolDispatcher

_SYSTEM = (
    "You are the tool-use driver of an autonomous system. You are given an objective and a "
    "list of TOOLS. Work toward the objective one step at a time.\n"
    "Reply with ONLY a JSON object, no prose. Either:\n"
    '  {"op": "<adapter.verb>", "args": { ... }}   to call one tool, or\n'
    '  {"done": true, "summary": "<what was accomplished>"}   when the objective is met.\n'
    "Call exactly one tool per reply. Do not invent ops that are not in the TOOLS list."
)

_EXCERPT = 600


@dataclass
class ToolLoopResult:
    ok: bool
    done: bool
    iterations: int
    summary: str
    transcript: list[dict[str, Any]] = field(default_factory=list)
    denials: int = 0
    # the non-ALLOW PolicyDecision objects the loop saw, in order — the caller
    # logs these as POLICY_DECISION events (the loop itself does no logging).
    decisions: list[Any] = field(default_factory=list)


class ToolLoop:
    def __init__(
        self,
        dispatcher: ToolDispatcher,
        llm: Any,
        *,
        max_iters: int = 6,
        parse_budget: int = 2,
    ) -> None:
        self.dispatcher = dispatcher
        self.llm = llm
        self.max_iters = max_iters
        self.parse_budget = parse_budget

    def run(
        self, objective: str, ctx: DispatchContext, manifest_block: str
    ) -> ToolLoopResult:
        transcript: list[dict[str, Any]] = []
        decisions: list[Any] = []
        denials = 0
        parse_left = self.parse_budget

        for it in range(1, self.max_iters + 1):
            reply = self._ask(objective, manifest_block, transcript)
            try:
                turn = parse_json_object(reply)
            except ValueError as exc:
                parse_left -= 1
                transcript.append({"kind": "error", "error": f"unparseable reply: {exc}"})
                if parse_left <= 0:
                    return ToolLoopResult(False, False, it, "unparseable model replies",
                                          transcript, denials, decisions)
                continue

            if turn.get("done") is True:
                summary = str(turn.get("summary", "")).strip() or "done"
                transcript.append({"kind": "done", "summary": summary})
                return ToolLoopResult(True, True, it, summary, transcript, denials, decisions)

            op = str(turn.get("op", "")).strip()
            args = turn.get("args") if isinstance(turn.get("args"), dict) else {}
            if not op:
                parse_left -= 1
                transcript.append({"kind": "error", "error": "reply named no op"})
                if parse_left <= 0:
                    return ToolLoopResult(False, False, it, "model named no op",
                                          transcript, denials, decisions)
                continue

            transcript.append({"kind": "call", "op": op, "args": args})
            result, decision = self.dispatcher.run(op, args, ctx)
            if decision is not None and decision.decision != "ALLOW":
                denials += 1
                decisions.append(decision)
            transcript.append({
                "kind": "result", "op": op, "ok": result.ok, "trust": result.trust,
                "output_excerpt": ("" if result.output is None else str(result.output)[:_EXCERPT]),
                "error": result.error[:_EXCERPT],
            })

        return ToolLoopResult(False, False, self.max_iters, "iteration cap",
                              transcript, denials, decisions)

    # ------------------------------------------------------------------ #
    def _ask(self, objective: str, manifest_block: str, transcript: list[dict]) -> str:
        prompt = (
            f"OBJECTIVE\n{objective}\n\n{manifest_block}\n"
            f"TRANSCRIPT SO FAR ({len(transcript)} turn(s))\n"
            + (self._render(transcript) if transcript else "(nothing yet)\n")
            + "\nYour next JSON object:"
        )
        resp = self.llm.complete(system=_SYSTEM, prompt=prompt)
        return getattr(resp, "text", str(resp))

    @staticmethod
    def _render(transcript: list[dict]) -> str:
        lines = []
        for t in transcript:
            k = t.get("kind")
            if k == "call":
                lines.append(f"- call {t['op']} args={t['args']}")
            elif k == "result":
                lines.append(
                    f"  -> ok={t['ok']} trust={t['trust']} "
                    f"{t['output_excerpt'] or t['error']}"
                )
            elif k == "error":
                lines.append(f"- error: {t['error']}")
            elif k == "done":
                lines.append(f"- done: {t['summary']}")
        return "\n".join(lines) + "\n"


# convenience for the orchestrator: build a loop from the S spine lazily
def build_tool_loop(registry, policy, llm, *, max_iters: int = 6) -> ToolLoop:
    return ToolLoop(ToolDispatcher(registry, policy,
                                   risk_globs=getattr(policy, "risk_globs", None)),
                    llm, max_iters=max_iters)
