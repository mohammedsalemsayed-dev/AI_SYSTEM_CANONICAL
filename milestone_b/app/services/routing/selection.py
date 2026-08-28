"""Model-selection controller (MILESTONE_O_PLAN.md §2, DESIGN_TIGHTENING §7.2, §8).

Per `task_class`, decide when the eligible models + a fitted `WeightSet` + a
passing guardrail regression check justify flipping routing from the static table
to data-driven. The decision + the weight set persist to system memory; a canary
rollback (Milestone I) demotes back to static.
"""

from __future__ import annotations

import json

from app.schemas.contracts import MemoryRecord, WeightSet

MIN_ELIGIBLE_MODELS = 2
MIN_TRAIN = 40
MIN_VAL_ACC = 0.65


class Decision:
    def __init__(self, mode: str, why: str) -> None:
        self.mode = mode
        self.why = why


class ModelSelectionController:
    def __init__(self, memory, stats, registry) -> None:
        self._memory = memory
        self._stats = stats
        self._registry = registry

    # -- persistence -------------------------------------------- #
    def _put(self, kind: str, task_class: str, payload: dict) -> None:
        self._memory.put(MemoryRecord(
            tier="system", kind=kind, scope=task_class, trust="workspace",
            content=json.dumps(payload),
        ))

    def _latest(self, kind: str, task_class: str) -> dict | None:
        rows = [
            m for m in self._memory.all(tier="system")
            if m.kind == kind and m.scope == task_class
        ]
        if not rows:
            return None
        try:
            return json.loads(rows[-1].content)
        except Exception:  # noqa: BLE001 — a corrupt record -> treat as absent
            return None

    def set_weights(self, ws: WeightSet) -> None:
        self._put("weight_set", ws.task_class, ws.model_dump(mode="json"))

    def weights_for(self, task_class: str) -> WeightSet | None:
        raw = self._latest("weight_set", task_class)
        if not raw:
            return None
        try:
            return WeightSet.model_validate(raw)
        except Exception:  # noqa: BLE001
            return None

    def mode(self, task_class: str) -> str:
        raw = self._latest("selection_mode", task_class)
        return raw.get("mode", "static") if raw else "static"

    # -- decide ---------------------------------------------- #
    def evaluate(self, task_class: str, *, regression_check=None) -> Decision:
        eligible = self._stats.eligible_models(task_class) if self._stats else []
        if len(eligible) < MIN_ELIGIBLE_MODELS:
            return Decision("static", f"only {len(eligible)}/{MIN_ELIGIBLE_MODELS} eligible models")

        ws = self.weights_for(task_class)
        if ws is None:
            return Decision("static", "no fitted weight set")
        if ws.degenerate or ws.n_train < MIN_TRAIN:
            return Decision("static", f"weight set weak (n_train={ws.n_train}, degenerate={ws.degenerate})")
        if ws.val_accuracy < MIN_VAL_ACC:
            return Decision("static", f"val_accuracy {ws.val_accuracy:.2f} < {MIN_VAL_ACC}")

        if regression_check is not None:
            reg = regression_check()
            if not getattr(reg, "passed", False):
                return Decision("static", f"guardrail regression: {getattr(reg, 'why', 'failed')}")

        return Decision("data_driven",
                        f"{len(eligible)} eligible, n_train={ws.n_train}, "
                        f"val_acc={ws.val_accuracy:.2f}")

    def promote(self, task_class: str, *, regression_check=None, log=None, task_id="") -> Decision:
        d = self.evaluate(task_class, regression_check=regression_check)
        if d.mode == "data_driven":
            self._put("selection_mode", task_class, {"mode": "data_driven", "why": d.why})
        self._emit(log, task_id, task_class, d.mode, d.why)
        return d

    def demote(self, task_class: str, reason: str, *, log=None, task_id="") -> None:
        self._put("selection_mode", task_class, {"mode": "static", "why": reason})
        self._emit(log, task_id, task_class, "static", reason)

    def _emit(self, log, task_id, task_class, mode, why) -> None:
        if log is None:
            return
        from app.events.log import EventKind

        ws = self.weights_for(task_class)
        log.append(task_id, EventKind.SELECTION, {
            "task_class": task_class, "mode": mode, "why": why,
            "n_train": ws.n_train if ws else 0,
            "val_accuracy": ws.val_accuracy if ws else 0.0,
        })
