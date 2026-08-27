"""The fixed escalation ladder (DESIGN_TIGHTENING.md §4, MILESTONE_D_PLAN.md §2).

    inspect -> change_strategy -> critic -> research -> stronger_model -> ask_user

Milestone D implements `inspect` (diagnose + log), `change_strategy` (force a
re-plan, bounded), and `ask_user` (pause). `critic` / `research` /
`stronger_model` are stubs that log and advance — Milestones E and G fill them.
The orchestrator calls `advance()` repeatedly on a STALLED / LOOP_RISK step until
it gets an action it can carry out.
"""

from __future__ import annotations

from dataclasses import dataclass

RUNGS = ("inspect", "change_strategy", "critic", "research", "stronger_model", "ask_user")


@dataclass
class Rung:
    name: str
    actionable: bool  # can the orchestrator do something, or is it a log-and-advance stub


class Ladder:
    def __init__(self, max_replans: int = 2) -> None:
        self._i = 0
        self.max_replans = max_replans
        self.replans_used = 0

    @property
    def current(self) -> str:
        return RUNGS[min(self._i, len(RUNGS) - 1)]

    def advance(self) -> Rung:
        """Return the next rung to act on. `inspect` and the stub rungs are
        reported as non-actionable (caller logs and calls advance again);
        `change_strategy` is actionable only while re-plans remain."""
        name = RUNGS[min(self._i, len(RUNGS) - 1)]
        self._i += 1
        if name == "change_strategy":
            if self.replans_used < self.max_replans:
                self.replans_used += 1
                return Rung("change_strategy", actionable=True)
            return Rung("change_strategy", actionable=False)  # exhausted -> advance
        if name == "ask_user":
            return Rung("ask_user", actionable=True)
        return Rung(name, actionable=False)

    def exhausted(self) -> bool:
        return self._i >= len(RUNGS)
