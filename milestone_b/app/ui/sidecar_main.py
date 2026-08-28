"""Frozen-friendly entrypoint for the desktop-shell server (MILESTONE_H_TAURI_PLAN.md §2).

This is what PyInstaller builds into `nexus-server` and what the Tauri shell
spawns as a sidecar. It differs from `run_ui.py` only in its defaults:

  * `--db` defaults to the per-user data path (`app.ui.paths.default_db_path()`),
    and its parent directory is created;
  * `--port` defaults to `NEXUS_PORT` or 8770;
  * task submission is **off** unless `NEXUS_ALLOW_SUBMIT=1` (or `--allow-submit`).

Everything else is `app.ui.server` unchanged.
"""

from __future__ import annotations

import argparse
import os
import sys

from app.ui.paths import default_db_path
from app.ui.server import serve


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="nexus-server")
    ap.add_argument("--db", default=None, help="event-log SQLite path (default: per-user data dir)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("NEXUS_PORT", "8770")))
    ap.add_argument("--allow-submit", action="store_true",
                    help="wire POST /api/tasks (also enabled by NEXUS_ALLOW_SUBMIT=1)")
    return ap


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    db = args.db or str(default_db_path())
    from pathlib import Path

    Path(db).parent.mkdir(parents=True, exist_ok=True)

    allow_submit = args.allow_submit or os.environ.get("NEXUS_ALLOW_SUBMIT") == "1"
    runner = None
    if allow_submit:
        from app.ui.run_ui import _build_runner

        runner = _build_runner(db)

    srv = serve(db, host=args.host, port=args.port, runner=runner)
    print(
        f"nexus-server on http://{args.host}:{srv.server_address[1]}  "
        f"(db={db}, submit={'on' if runner else 'off'})",
        flush=True,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
