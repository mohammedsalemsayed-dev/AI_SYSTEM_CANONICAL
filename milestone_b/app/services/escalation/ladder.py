"""The fixed escalation ladder (DESIGN_TIGHTENING.md §4, MILESTONE_D_PLAN.md §2).

    inspect -> change_strategy -> critic -> research -> stronger_model -> ask_user

Milestone D implements `inspect` (diagnose + log), `change_strategy` (force a
re-plan, bounded), and `ask_user` (pause). Milestone E fills `critic` / `research`
(actionable when the role is wired); Milestone G fills `stronger_model`
(actionable when a `Router` with an untried stronger provider is wired).
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
    def __init__(
        self,
        max_replans: int = 2,
        *,
        has_critic: bool = False,
        has_researcher: bool = False,
        has_stronger_model: bool = False,
    ) -> None:
        self._i = 0
        self.max_replans = max_replans
        self.replans_used = 0
        self.has_critic = has_critic
        self.has_researcher = has_researcher
        self.has_stronger_model = has_stronger_model

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
        if name == "critic":
            return Rung("critic", actionable=self.has_critic)
        if name == "research":
            return Rung("research", actionable=self.has_researcher)
        if name == "stronger_model":
            return Rung("stronger_model", actionable=self.has_stronger_model)
        if name == "ask_user":
            return Rung("ask_user", actionable=True)
        return Rung(name, actionable=False)

    def exhausted(self) -> bool:
        return self._i >= len(RUNGS)
