"""Premise run WITH local-first escalation, through the real Orchestrator.

Each seeded bug task runs the full pipeline:
  Interpreter + Planner + Builder = local qwen3:8b
  Verifier                        = T0 in the Docker sandbox
  fallback_builder                = agent_sdk (cloud) -- one retry on T0 fail

Tally:
  local      COMPLETED with NO escalation  -> solved fully on-device
  escalated  COMPLETED after an ESCALATION -> local failed, cloud finished
  failed     never reached COMPLETED

    python -m tests.premise.make_seeded_repos          # once
    python -m tests.premise.bench_local_first          # all seeded tasks
    python -m tests.premise.bench_local_first 01 03 07 # a subset by id prefix

Writes LOCAL_FIRST_BENCH.md. Uses the Claude subscription for escalations
(no per-token spend, subject to rate limits).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.llm import get_llm
from app.orchestration.orchestrator import Orchestrator
from app.services.build import get_builder
from app.services.interpret.interpreter import Interpreter
from app.services.plan.planner import Planner
from app.services.policy.engine import PolicyEngine
from app.services.verify.verifier_t0 import VerifierT0

_OUT = Path("LOCAL_FIRST_BENCH.md")
_LOCAL = "local:qwen3:8b"


def _run_one(task: dict, full: bool = False) -> dict:
    ws = str(Path(task["workspace"]).resolve())
    log = EventLog()
    interp = get_llm(_LOCAL)
    orch = Orchestrator(
        log, Interpreter(interp), Planner(get_llm(_LOCAL)),
        get_builder(_LOCAL), VerifierT0(), PolicyEngine(),
    )
    orch.fallback_builder = get_builder("agent_sdk")
    if full:
        from app.cli.full_stack import wire_full_stack

        wire_full_stack(orch, verbose=False)

    t0 = time.time()
    try:
        result = orch.run(task["request"], ws)
        state = result.state
    except Exception as exc:  # noqa: BLE001
        state = f"CRASH: {exc!r}"
    secs = round(time.time() - t0, 1)

    ev = log.all()
    escalated = any(e.kind == EventKind.ESCALATION
                    and e.payload.get("reason") == "verification failed" for e in ev)
    verds = [e.payload.get("overall") for e in ev if e.kind == EventKind.VERIFICATION]
    bucket = ("local" if state == "COMPLETED" and not escalated
              else "escalated" if state == "COMPLETED" and escalated
              else "failed")
    log.close()
    return {"id": task["id"], "state": state, "bucket": bucket,
            "escalated": escalated, "verds": verds, "secs": secs}


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    full = "--full" in argv
    argv = [a for a in argv if a != "--full"]
    tasks = json.loads(Path("tests/premise/tasks.seeded.json").read_text("utf-8"))
    tasks = [t for t in tasks if Path(t["workspace"]).is_dir()]
    if argv:
        tasks = [t for t in tasks if any(t["id"].startswith(a) for a in argv)]
    if not tasks:
        print("no seeded repos — run: python -m tests.premise.make_seeded_repos",
              file=sys.stderr)
        return 2

    rows = []
    for t in tasks:
        r = _run_one(t, full=full)
        rows.append(r)
        print(f"  {r['id']:26} {r['bucket']:10} state={r['state']:14} "
              f"verds={r['verds']} {r['secs']}s")

    n = len(rows)
    loc = sum(r["bucket"] == "local" for r in rows)
    esc = sum(r["bucket"] == "escalated" for r in rows)
    fail = sum(r["bucket"] == "failed" for r in rows)
    title = "# Premise run — local-first with cloud escalation" + (" (FULL stack)" if full else "")
    lines = [
        title, "",
        f"Full pipeline per task: Interpreter + Planner + Builder = `{_LOCAL}`; "
        "Verifier = T0 in Docker; fallback = `agent_sdk` (one retry on T0 fail)"
        + ("; plus Router + Critic + T2 verifier + memory/experience." if full else "."), "",
        f"- **solved on-device (local only): {loc}/{n}**",
        f"- solved after escalation to cloud: {esc}/{n}",
        f"- failed (neither): {fail}/{n}",
        f"- end-to-end success (local + escalated): **{loc + esc}/{n}**", "",
        "| task | outcome | final state | verifications | wall_s |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['id']} | {r['bucket']} | {r['state']} | "
                     f"{r['verds']} | {r['secs']} |")
    _OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nlocal {loc}/{n}  escalated {esc}/{n}  failed {fail}/{n}  -> wrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
