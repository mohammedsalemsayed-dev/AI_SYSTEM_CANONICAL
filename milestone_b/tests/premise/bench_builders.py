"""Benchmark local Builder candidates through the REAL LocalBuilder loop.

Not "which model writes the best function" — this runs each model through the
exact agentic loop, tools, and contracts the system uses, on the seeded bug
repos, then independently verifies the diff. Produces BUILDER_BENCH.md.

    python -m tests.premise.make_seeded_repos          # once, writes premise_repos/
    python -m tests.premise.bench_builders qwen3:8b qwen2.5-coder:7b llama3.1:8b

Scores per model (aggregated over the tasks):
  fixed            tasks whose diff passes independent verification  (the headline)
  tool_valid_rate  tool_calls that parsed / all model turns
  bad_arg_rate     known-tool calls with missing/bad required args / tool_calls
  edit_fail_rate   edit_file calls whose `old` was not found / edits attempted
  finished_rate    tasks where the model called finish()
  turn_cap_rate    tasks that hit the turn cap
  avg_turns / avg_wall_s / avg_tokens
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from app.schemas.contracts import PlanStep, TaskContract
from app.services.build.local_builder import LocalBuilder
from app.services.build.workspace_copy import apply_diff, cleanup, copy_workspace

_OUT = Path("BUILDER_BENCH.md")
_TEST_RE = re.compile(r"test_\w+\.py")


def _target(request: str) -> str:
    m = _TEST_RE.search(request)
    return m.group(0) if m else ""


def _verify(original_ws: str, diff: str, target: str) -> bool:
    if not diff.strip():
        return False
    fresh = copy_workspace(original_ws, prefix="bench_verify_")
    try:
        if not apply_diff(fresh, diff):
            return False
        import subprocess

        argv = [sys.executable, "-m", "pytest", "-q"] + (target.split() if target else [])
        p = subprocess.run(argv, cwd=fresh, capture_output=True, text=True, timeout=120)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        cleanup(fresh)


def run_one(model: str, task: dict) -> dict:
    ws0 = str(Path(task["workspace"]).resolve())
    target = _target(task["request"])
    contract = TaskContract(
        task_id="bench", original_request=task["request"], objective=task["request"],
        task_class="debug", success_criteria=["the failing test passes"],
        required_evidence=[f"T0: pytest {target} passes"],
    )
    step = PlanStep(intent="make the failing test pass with the smallest source change",
                    expected_artifact_delta="edit the buggy module",
                    required_capability="fs.write")

    ws = copy_workspace(ws0, prefix="bench_build_")
    try:
        builder = LocalBuilder(model=model)
        out = builder.execute(task_id="bench", step=step, contract=contract, workspace=ws)
        m = builder.metrics.as_dict()
    finally:
        cleanup(ws)

    verified = _verify(ws0, out.diff, target)
    m.update(id=task["id"], verified=verified, diff_bytes=len(out.diff.encode("utf-8")),
             build_error=out.error or "")
    return m


def aggregate(model: str, rows: list[dict]) -> dict:
    n = len(rows)
    calls = sum(r["tool_calls"] for r in rows)
    turns = sum(r["turns"] for r in rows)
    edits = sum(r["edits"] + r["edit_failures"] for r in rows)
    return {
        "model": model,
        "fixed": f"{sum(r['verified'] for r in rows)}/{n}",
        "tool_valid_rate": round(calls / turns, 2) if turns else 0.0,
        "bad_arg_rate": round(sum(r["bad_arg_calls"] for r in rows) / calls, 2) if calls else 0.0,
        "confusion_rate": round(sum(r["tool_confusion"] for r in rows) / calls, 2) if calls else 0.0,
        "edit_fail_rate": round(sum(r["edit_failures"] for r in rows) / edits, 2) if edits else 0.0,
        "finished_rate": round(sum(r["finished"] for r in rows) / n, 2) if n else 0.0,
        "turn_cap_rate": round(sum(r["hit_turn_cap"] for r in rows) / n, 2) if n else 0.0,
        "avg_turns": round(turns / n, 1) if n else 0.0,
        "avg_wall_s": round(sum(r["wall_s"] for r in rows) / n, 1) if n else 0.0,
        "avg_tokens": round(sum(r["in_tokens"] + r["out_tokens"] for r in rows) / n) if n else 0,
    }


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    models = argv or ["qwen3:8b", "qwen2.5-coder:7b", "llama3.1:8b"]
    tasks = json.loads(Path("tests/premise/tasks.seeded.json").read_text("utf-8"))
    tasks = [t for t in tasks if Path(t["workspace"]).is_dir()]
    if not tasks:
        print("no seeded repos — run: python -m tests.premise.make_seeded_repos", file=sys.stderr)
        return 2

    print(f"{len(models)} model(s) x {len(tasks)} task(s)")
    all_rows: dict[str, list[dict]] = {}
    detail: list[dict] = []
    for model in models:
        rows = []
        for t in tasks:
            t0 = time.time()
            r = run_one(model, t)
            rows.append(r)
            print(f"  {model:22} {t['id']:26} "
                  f"{'FIXED' if r['verified'] else 'no   '} "
                  f"turns={r['turns']:2} calls={r['tool_calls']:2} "
                  f"bad_args={r['bad_arg_calls']} edit_fail={r['edit_failures']} "
                  f"{round(time.time()-t0,1)}s")
        all_rows[model] = rows
        detail.extend(rows)

    aggs = [aggregate(m, all_rows[m]) for m in models]
    _write(aggs, detail)
    print(f"\nwrote {_OUT}")
    return 0


def _write(aggs: list[dict], detail: list[dict]) -> None:
    cols = ["model", "fixed", "tool_valid_rate", "bad_arg_rate", "confusion_rate",
            "edit_fail_rate", "finished_rate", "turn_cap_rate", "avg_turns",
            "avg_wall_s", "avg_tokens"]
    lines = ["# Local Builder benchmark", "",
             "Each model run through `LocalBuilder` (same loop / tools / contracts as the "
             "real system) on the seeded bug repos; diff independently verified with pytest.",
             "", "| " + " | ".join(cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for a in aggs:
        lines.append("| " + " | ".join(str(a[c]) for c in cols) + " |")
    lines += ["", "## Per-task", "",
              "| model | task | fixed | turns | calls | bad_args | edit_fail | finished | wall_s |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in detail:
        lines.append(
            f"| {r['model']} | {r['id']} | {'yes' if r['verified'] else 'no'} | "
            f"{r['turns']} | {r['tool_calls']} | {r['bad_arg_calls']} | "
            f"{r['edit_failures']} | {'yes' if r['finished'] else 'no'} | {r['wall_s']} |")
    _OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
