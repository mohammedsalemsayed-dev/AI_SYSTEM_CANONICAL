"""Milestone O — offline routing-weight fitter (MILESTONE_O_PLAN.md §2, §5).

Reads a populated `RouteStatsStore` (system memory), fits a logistic-regression
`WeightSet` per `task_class`, prints the per-class validation accuracy + weights,
and (with `--write`) persists each `WeightSet` via `ModelSelectionController`.

    python -m tests.benchmark.fit_weights --memory nexus/route_stats.db --write

NOT run as part of the test suite — needs a real scored-run corpus (produce one
with `tests/benchmark/seed_model.py` on the subscription).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", default=":memory:", help="sqlite path of the RouteStatsStore")
    ap.add_argument("--min-per-class", type=int, default=20)
    ap.add_argument("--write", action="store_true", help="persist a WeightSet per class")
    args = ap.parse_args(argv)

    from app.services.memory.store import MemoryStore
    from app.services.routing.registry import ProviderRegistry
    from app.services.routing.stats import RouteStatsStore
    from app.services.routing.selection import ModelSelectionController
    from app.services.routing.weightfit import fit_weights, training_rows

    mem = MemoryStore(args.memory)
    stats = RouteStatsStore(mem)
    registry = ProviderRegistry()

    # group scored runs by task_class
    by_class: dict[str, list] = defaultdict(list)
    for m in mem.all(tier="system"):
        if m.kind != "model_run":
            continue
        try:
            r = json.loads(m.content)
        except Exception:  # noqa: BLE001
            continue
        by_class[r.get("task_class", "?")].append(m)

    controller = ModelSelectionController(mem, stats, registry) if args.write else None
    total = 0
    for tc, rows in sorted(by_class.items()):
        if len(rows) < args.min_per_class:
            print(f"{tc:18s} {len(rows):4d} runs  — below --min-per-class, skipped")
            continue
        # reuse training_rows but filtered to this class by monkey-scoping the store view
        class _View:
            _memory = _ClassMem(mem, tc)

        trows = training_rows(_View(), registry)
        ws = fit_weights(trows, task_class=tc)
        flag = " DEGENERATE" if ws.degenerate else ""
        print(f"{tc:18s} n_train={ws.n_train:4d}  val_acc={ws.val_accuracy:.3f}{flag}")
        print("   weights: " + ", ".join(f"{k}={v:+.3f}" for k, v in ws.weights.items()))
        if controller is not None and not ws.degenerate:
            controller.set_weights(ws)
            total += 1

    if controller is not None:
        print(f"\nwrote {total} weight set(s) to {args.memory}")
    mem.close()
    return 0


class _ClassMem:
    """A memory-store view restricted to one task_class's model_run rows."""

    def __init__(self, mem, task_class: str) -> None:
        self._mem = mem
        self._tc = task_class

    def all(self, *, tier=None, **_kw):
        out = []
        for m in self._mem.all(tier=tier):
            if m.kind == "model_run":
                try:
                    if json.loads(m.content).get("task_class") != self._tc:
                        continue
                except Exception:  # noqa: BLE001
                    continue
            out.append(m)
        return out


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
