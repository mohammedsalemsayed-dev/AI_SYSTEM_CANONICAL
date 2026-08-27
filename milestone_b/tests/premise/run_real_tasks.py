"""Day 10 — the premise test (MILESTONE_B_PLAN.md section 7).

Runs a set of real tasks with the real providers (Anthropic LLM + Claude Agent
SDK builder), records metrics, and writes SLICE_FINDINGS.md.

    pip install -e ".[llm]"
    export SLICE_LLM_MODEL=<current-model-id>      # see the claude-api skill
    python -m tests.premise.run_real_tasks tests/premise/tasks.example.json

Requires working Anthropic credentials / Agent SDK auth in the environment.
`diff_correct` cannot be judged automatically — each task's diff and timeline are
saved under findings_artifacts/<id>/ for you to score by hand, then fill the
column in SLICE_FINDINGS.md.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.orchestration.orchestrator import Orchestrator
from app.services.build.agent_sdk import AgentSDKBuilder
from app.services.interpret.interpreter import Interpreter
from app.services.plan.planner import Planner
from app.services.policy.engine import PolicyEngine
from app.services.verify.verifier_t0 import VerifierT0
from app.services.workspace.listing import is_git_repo
from app.llm.anthropic_client import AnthropicLLM

_ARTIFACTS = Path("findings_artifacts")
_FINDINGS = Path("SLICE_FINDINGS.md")


def _unaided_t0(events: list) -> bool:
    for e in events:
        if e.kind == EventKind.CONTRACT:
            ev = e.payload.get("required_evidence", [])
            amb = e.payload.get("ambiguity", [])
            has_t0 = any(("t0" in x.lower() and "pytest" in x.lower()) for x in ev)
            return bool(has_t0 and not amb)
    return False


def _tokens(events: list) -> int:
    return sum(
        e.payload.get("input_tokens", 0) + e.payload.get("output_tokens", 0)
        for e in events
        if e.kind == EventKind.MODEL_RUN
    )


def _save_artifacts(log: EventLog, task_id: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    events = log.read(task_id)
    (out / "timeline.txt").write_text(
        "\n".join(f"{e.seq:>3} {e.kind} {json.dumps(e.payload)[:400]}" for e in events),
        encoding="utf-8",
    )
    for e in events:
        if e.kind == EventKind.ARTIFACT and e.payload.get("diff"):
            (out / "change.diff").write_text(e.payload["diff"], encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    tasks = json.loads(Path(argv[0]).read_text(encoding="utf-8"))

    _ARTIFACTS.mkdir(exist_ok=True)
    db = _ARTIFACTS / "events.db"
    if db.exists():
        db.unlink()
    log = EventLog(db)
    llm = AnthropicLLM()
    orch = Orchestrator(
        log,
        Interpreter(llm),
        Planner(llm),
        AgentSDKBuilder(),
        VerifierT0(),
        PolicyEngine(),
    )

    rows: list[dict] = []
    for spec in tasks:
        tid_label = spec["id"]
        ws = str(Path(spec["workspace"]).resolve())
        if not is_git_repo(ws):
            rows.append({"id": tid_label, "state": "SKIPPED (not a git repo)", "verify": "-", "secs": 0, "tokens": 0, "unaided_t0": "-"})
            continue
        t0 = time.time()
        try:
            result = orch.run(spec["request"], ws)
            state = result.state
        except Exception as exc:  # noqa: BLE001
            state = f"CRASH: {exc!r}"
            result = None
        secs = round(time.time() - t0, 1)

        events = log.read(result.task_id) if result else []
        verify = "-"
        for e in events:
            if e.kind == EventKind.VERIFICATION:
                verify = e.payload.get("overall", "-")
        if result:
            _save_artifacts(log, result.task_id, _ARTIFACTS / tid_label)
        rows.append(
            {
                "id": tid_label,
                "state": state,
                "verify": verify,
                "secs": secs,
                "tokens": _tokens(events),
                "unaided_t0": "yes" if _unaided_t0(events) else "no",
            }
        )

    _write_findings(rows)
    log.close()
    print(f"wrote {_FINDINGS} and {_ARTIFACTS}/<id>/ ; fill the diff_correct column by hand")
    return 0


def _write_findings(rows: list[dict]) -> None:
    n = len(rows)
    verified_pass = sum(1 for r in rows if r["verify"] == "pass")
    unaided = sum(1 for r in rows if r["unaided_t0"] == "yes")
    lines = [
        "# Slice Findings — Milestone B premise test",
        "",
        f"Ran {n} real tasks with AnthropicLLM + AgentSDKBuilder + VerifierT0.",
        "",
        "| id | final state | T0 verify | wall-clock s | tokens | unaided T0 criterion | diff_correct (fill by hand) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['id']} | {r['state']} | {r['verify']} | {r['secs']} | {r['tokens']} | {r['unaided_t0']} | ? |"
        )
    lines += [
        "",
        f"- T0 verify == pass: **{verified_pass}/{n}**",
        f"- interpreter produced a usable T0 criterion unaided: **{unaided}/{n}**",
        "- diff_correct: score each `findings_artifacts/<id>/change.diff` yourself, then update the table.",
        "",
        "## Read the result (MILESTONE_B_PLAN.md section 7)",
        "",
        "- **diff_correct >= ~70%** with a clean T0 gate -> premise holds. Proceed to Milestone C;",
        "  start pulling from DESIGN_TIGHTENING.md section 14 (security seam 14.3, then Tier-A sandbox 14.6).",
        "- **diff_correct ~50-70%** -> executor is fine, weakness is upstream. Invest in interpretation +",
        "  planning + verification (section 14.1) before C.",
        "- **diff_correct < ~50%** even with the cloud builder -> the loop design is wrong, not the model.",
        "  Reassess scope before building more infrastructure.",
    ]
    _FINDINGS.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
