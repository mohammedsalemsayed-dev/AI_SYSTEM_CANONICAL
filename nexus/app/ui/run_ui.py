"""Desktop-shell entrypoint (MILESTONE_H_PLAN.md §2).

    python -m app.ui.run_ui --db nexus/slice.db --port 8770
    python -m app.ui.run_ui --db nexus/slice.db --allow-submit   # wires POST /api/tasks

Serves an existing event-log DB read-only. `--allow-submit` also constructs an
Orchestrator over the same DB and exposes `POST /api/tasks`; a submitted task
still passes every policy / approval / budget gate.
"""

from __future__ import annotations

import argparse
import sys

from app.ui.server import serve


def _build_runner(db_path: str):
    # local-first Builder + cloud escalation + full roster, run on a background
    # thread so POST /api/tasks returns immediately. See app/ui/runner.py.
    from app.ui.runner import build_task_runner

    return build_task_runner(db_path)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="path to the event-log SQLite DB")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--allow-submit", action="store_true",
                    help="wire POST /api/tasks to a real Orchestrator over --db")
    args = ap.parse_args(argv)

    runner = _build_runner(args.db) if args.allow_submit else None
    srv = serve(args.db, host=args.host, port=args.port, runner=runner)
    print(f"desktop shell on http://{args.host}:{srv.server_address[1]}  (db={args.db}, "
          f"submit={'on' if runner else 'off'})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
        srv.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
