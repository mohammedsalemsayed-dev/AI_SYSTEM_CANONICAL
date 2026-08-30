"""ProgressService — classify each step from hard signals + a novel-motion guard.

Deterministic. Loop and resource classifications are supplied by the loop
detector (day 3-4) and the budget tracker (day 8) as override flags; everything
else comes from `signals.hard_progress` and the no-progress run length
(MILESTONE_D_PLAN.md 2, 7).
"""

from __future__ import annotations

from app.schemas.contracts import ProgressEvent
from app.services.progress.signals import StepMeasurement, hard_progress

DEFAULT_PATIENCE_STEPS = 3  # K in "K steps -> SLOW_PROGRESS, +K -> STALLED"


class ProgressService:
    def __init__(self, task_id: str, patience_steps: int = DEFAULT_PATIENCE_STEPS) -> None:
        self.task_id = task_id
        self.k = patience_steps
        self._history: list[StepMeasurement] = []
        self._touched: set[str] = set()
        self._no_progress_run = 0

    def observe(
        self,
        m: StepMeasurement,
        *,
        loop_flag: bool = False,
        resource_flag: bool = False,
    ) -> ProgressEvent:
        prev = self._history[-1] if self._history else None

        if prev is None:
            # the baseline measurement — establishes the reference, not scored
            self._history.append(m)
            self._touched.update(m.changed_paths)
            return ProgressEvent(
                task_id=self.task_id,
                step_index=m.step_index,
                classification="RESOURCE_LIMITED" if resource_flag else "HEALTHY_PROGRESS",
                signals=[],
                hard_progress=False,
                no_progress_run=0,
                detail="baseline measurement",
            )

        signals = hard_progress(prev, m, self._touched)
        made_progress = bool(signals)

        if made_progress:
            self._no_progress_run = 0
        else:
            self._no_progress_run += 1

        classification = self._classify(
            made_progress, m.moved, loop_flag, resource_flag
        )

        self._history.append(m)
        self._touched.update(m.changed_paths)

        return ProgressEvent(
            task_id=self.task_id,
            step_index=m.step_index,
            classification=classification,
            signals=signals,
            hard_progress=made_progress,
            no_progress_run=self._no_progress_run,
            detail=self._detail(classification, signals),
        )

    # ------------------------------------------------------------------ #
    def _classify(
        self, made_progress: bool, moved: bool, loop_flag: bool, resource_flag: bool
    ) -> str:
        if loop_flag:
            return "LOOP_RISK"
        if resource_flag:
            return "RESOURCE_LIMITED"
        if made_progress:
            return "HEALTHY_PROGRESS"
        run = self._no_progress_run
        if not moved:
            # a builder producing literally nothing stalls faster
            return "STALLED" if run >= self.k else "SLOW_PROGRESS"
        if run >= 2 * self.k:
            return "STALLED"
        if run >= self.k:
            return "SLOW_PROGRESS"
        return "HEALTHY_PROGRESS"  # benefit of the doubt for the first K steps

    @staticmethod
    def _detail(classification: str, signals: list[str]) -> str:
        if signals:
            return "progress: " + ", ".join(signals)
        return f"no hard-progress signal ({classification})"

    @property
    def no_progress_run(self) -> int:
        return self._no_progress_run
