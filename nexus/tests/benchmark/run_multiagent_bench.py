"""Milestone E days 13-14 — single-agent vs single+Critic benchmark.

Runs each task in a task file twice: {Builder} and {Builder + Critic}. Compares
verified success, retry (rework) rate, wall-clock. Writes MULTIAGENT_FINDINGS.md
and decides whether the Critic meets its §9 promotion criterion.

    pip install -e ".[llm]"
    python -m tests.benchmark.run_multiagent_bench tests/premise/tasks.real.json

Needs a logged-in `claude` CLI (uses the subscription via the Agent SDK), same
as the premise harness.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from tests.premise.run_real_tasks import _load_env_local  # reuse the .env.local loader

_FINDINGS = Path("MULTIAGENT_FINDINGS.md")


def _build(with_critic: bool):
    from app.events.log import EventLog
    from app.llm import get_llm
    from app.orchestration.orchestrator import Orchestrator
    from app.services.agents.critic import Critic
    from app.services.build.agent_sdk import AgentSDKBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    log = EventLog(":memory:")
    llm = get_llm("agent_sdk")
    orch = Orchestrator(
        log, Interpreter(llm), Planner(llm), AgentSDKBuilder(),
        VerifierT0(require_isolation=True), PolicyEngine(),
        critic=Critic(get_llm("agent_sdk")) if with_critic else None,
    )
    return orch, log


def _run_once(spec, with_critic):
    from app.events.log import EventKind

    orch, log = _build(with_critic)
    t0 = time.time()
    try:
        result = orch.run(spec["request"], str(Path(spec["workspace"]).resolve()))
        state = result.state
    except Exception as exc:  # noqa: BLE001
        state, result = f"CRASH {exc!r}", None
    secs = round(time.time() - t0, 1)
    events = log.read(result.task_id) if result else []
    verified = any(
        e.kind == EventKind.VERIFICATION
        and e.payload.get("tier") == "T0"
        and e.payload.get("overall") == "pass"
        for e in events
    )
    retries = sum(1 for e in events if e.kind == EventKind.CRITIC) + sum(
        1 for e in events if e.kind == EventKind.ESCALATION
    )
    return {"state": state, "verified": verified, "secs": secs, "retries": retries}


def main(argv=None) -> int:
    _load_env_local()
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    tasks = json.loads(Path(argv[0]).read_text(encoding="utf-8"))

    rows = []
    for spec in tasks:
        base = _run_once(spec, with_critic=False)
        wc = _run_once(spec, with_critic=True)
        rows.append({"id": spec["id"], "base": base, "critic": wc})
        print(f"{spec['id']}: base={base['verified']} critic={wc['verified']}")

    _write(rows)
    print(f"wrote {_FINDINGS}")
    return 0


def _write(rows) -> None:
    n = len(rows)
    base_pass = sum(r["base"]["verified"] for r in rows)
    crit_pass = sum(r["critic"]["verified"] for r in rows)
    delta = (crit_pass - base_pass) / n if n else 0.0
    lines = [
        "# Multi-agent findings — single-agent vs single + Critic",
        "",
        f"Ran {n} tasks each way on the Claude subscription.",
        "",
        "| id | base verified | +critic verified | base s | +critic s | base retries | +critic retries |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        b, c = r["base"], r["critic"]
        lines.append(
            f"| {r['id']} | {b['verified']} | {c['verified']} | {b['secs']} | {c['secs']} "
            f"| {b['retries']} | {c['retries']} |"
        )
    lines += [
        "",
        f"- base verified: **{base_pass}/{n}**",
        f"- +critic verified: **{crit_pass}/{n}**",
        f"- verified-success delta: **{delta:+.2f}**",
        "",
        "## Promotion call (MILESTONE_E_PLAN §7 / design-notes §9)",
        "",
        "Promote the Critic to default-on when: verified success **+>= 0.05**, OR",
        "**>= 1 real defect caught per 10 tasks** (a task the Critic's retry turned from",
        "fail to pass). Below that, keep it opt-in.",
        "",
        f"-> verified-success delta {delta:+.2f} "
        + ("**meets**" if delta >= 0.05 else "does **not** meet")
        + " the promote bar on this sample.",
    ]
    _FINDINGS.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
