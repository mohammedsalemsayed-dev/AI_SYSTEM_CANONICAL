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


def _warm_models_async() -> None:
    """Fire a 1-token generate at the local models so the first real request
    isn't a 40s cold model-load. Best-effort, daemon thread, silent on failure.
    Skip with NEXUS_NO_WARMUP=1."""
    if os.environ.get("NEXUS_NO_WARMUP") == "1":
        return
    import threading

    def _warm() -> None:
        import json as _json
        import urllib.request as _u

        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        try:
            from app.ui.runner import _LOCAL, _local_coder

            models = {_LOCAL.split(":", 1)[1], _local_coder().split(":", 1)[1]}
        except Exception:  # noqa: BLE001
            models = {"qwen3:8b"}
        for m in models:
            try:
                body = _json.dumps({"model": m, "prompt": "ok", "stream": False,
                                    "keep_alive": "30m", "options": {"num_predict": 1}}).encode()
                req = _u.Request(f"{host}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
                _u.urlopen(req, timeout=180).read()
                print(f"warmed {m}", flush=True)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=_warm, daemon=True, name="nexus-warmup").start()


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)

    db = args.db or str(default_db_path())
    from pathlib import Path

    Path(db).parent.mkdir(parents=True, exist_ok=True)

    # reap our own leaked temp dirs from previous (hard-killed) runs
    try:
        from app.ui.tmpsweep import sweep_stale_tempdirs

        n = sweep_stale_tempdirs()
        if n:
            print(f"tmp sweep: removed {n} stale dir(s)", flush=True)
    except Exception:  # noqa: BLE001 — housekeeping must never block startup
        pass

    allow_submit = args.allow_submit or os.environ.get("NEXUS_ALLOW_SUBMIT") == "1"
    runner = None
    if allow_submit:
        from app.ui.runner import build_task_runner

        runner = build_task_runner(db)
        _warm_models_async()

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
