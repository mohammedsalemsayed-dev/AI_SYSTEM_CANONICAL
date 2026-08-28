"""Milestone G day 13 — offline model-eligibility seeder (DESIGN_TIGHTENING §7.2).

The data-driven router only considers a `(task_class, model)` pair once it has
>= 20 *scored* runs (verification tier >= T1). Waiting for that to accrue from
live traffic is slow, and it is the wrong signal for a brand-new model. This
harness replays a frozen task set with known T0 oracles against one named model,
writes the resulting **scored** `ModelRunRecord`s into a `MemoryStore`
(system tier) via `RouteStatsStore`, and reports the aggregates the router will
see.

    pip install -e ".[llm]"
    python -m tests.benchmark.seed_model agent_sdk tests/premise/tasks.seeded.json \
        --memory milestone_b/route_stats.db

Needs a logged-in `claude` CLI (subscription via the Agent SDK), like the premise
harness. NOT run as part of the test suite — it makes real model calls.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _run_once(model_id: str, task: dict) -> tuple[str, str, bool, float, str]:
    """Run one premise task through the real slice; return
    (task_class, model, verified_pass, latency_s, verification_tier)."""
    from app.events.log import EventKind, EventLog
    from app.llm import get_llm
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.agent_sdk import AgentSDKBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    log = EventLog(":memory:")
    llm = get_llm("agent_sdk")
    orch = Orchestrator(
        log, Interpreter(llm), Planner(llm), AgentSDKBuilder(),
        VerifierT0(), PolicyEngine(),
    )
    t0 = time.time()
    result = orch.run(task["request"], task["repo"])
    latency = time.time() - t0

    snap = log.read(result.task_id)
    contract = next((e.payload for e in snap if e.kind == EventKind.CONTRACT), {})
    verif = next(
        (e.payload for e in reversed(snap) if e.kind == EventKind.VERIFICATION), {}
    )
    return (
        contract.get("task_class", "code_edit_local"),
        model_id,
        result.verified,
        latency,
        verif.get("tier", "T0"),
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_id", help="provider id from the registry, e.g. agent_sdk")
    ap.add_argument("task_file", help="a premise task json (list of {request, repo, ...})")
    ap.add_argument("--memory", default=":memory:", help="sqlite path for the RouteStatsStore")
    ap.add_argument("--repeat", type=int, default=1, help="replays of the whole task set")
    args = ap.parse_args(argv)

    from tests.premise.run_real_tasks import _load_env_local

    _load_env_local()

    from app.services.memory.store import MemoryStore
    from app.services.routing.registry import ProviderRegistry
    from app.services.routing.stats import ELIGIBLE_MIN_RUNS, RouteStatsStore
    from app.schemas.contracts import ModelRunRecord

    spec = ProviderRegistry().get(args.model_id)
    model_name = (spec.model or spec.id) if spec else args.model_id

    tasks = json.loads(Path(args.task_file).read_text(encoding="utf-8"))
    mem = MemoryStore(args.memory)
    stats = RouteStatsStore(mem)

    scored = 0
    for _ in range(args.repeat):
        for task in tasks:
            tc, _model, ok, latency, tier = _run_once(args.model_id, task)
            run = ModelRunRecord(
                task_id="seed", role="builder", provider=args.model_id,
                model=model_name, latency_s=latency,
            )
            if stats.ingest(run, task_class=tc, verification_tier=tier, verification_pass=ok):
                scored += 1
            print(f"  {tc:16s} {model_name:20s} pass={ok!s:5s} {latency:6.1f}s tier={tier}")

    classes = {json.loads(m.content)["task_class"]
               for m in mem.all(tier="system") if m.kind == "model_run"}
    print(f"\nscored {scored} runs across {len(classes)} task classes")
    for tc in sorted(classes):
        agg = stats.aggregate(tc, model_name)
        elig = "ELIGIBLE" if stats.eligible(tc, model_name) else f"{agg['n']}/{ELIGIBLE_MIN_RUNS}"
        print(f"  {tc:16s} n={agg['n']:3d} success={agg['success_rate']:.0%} "
              f"lat_med={agg['latency_median']:.1f}s  [{elig}]")
    mem.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
