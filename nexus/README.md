# nexus/ — the code

The Python control plane, its tests, and the desktop shell. Run everything from
this directory.

## Layout

- `app/` — the control plane.
  - `app/orchestration/` — the state machine and orchestrator.
  - `app/services/` — verifier, local/cloud builders, policy engine, research,
    authoring (docx/pptx/pdf), repo intelligence, tool adapters.
  - `app/events/` — append-only event log + projections (SQLite or Postgres).
  - `app/cli/` — `run_task`, `demo`.
  - `app/ui/` — loopback HTTP/JSON API + a no-build frontend.
- `tests/` — `unit/ security/ integration/ regression/ fault/`. Offline and
  deterministic; base dependency is `pydantic`.
- `desktop/` — Tauri v2 shell + `build.py`, which bundles a PyInstaller-frozen
  `nexus-server` sidecar into a Windows installer.

## Run

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/                              # full suite
python -m app.cli.demo                               # scripted end-to-end, no network
python -m app.cli.run_task "<request>" --workspace <repo> --full --apply
python -m app.ui.run_ui --db nexus.db --port 8770    # -> http://127.0.0.1:8770
```

See the root [README](../README.md) for full setup (Ollama, Docker, the `claude`
CLI login), [../design/STATUS.md](../design/STATUS.md) for what is actually built
versus still a stub, and [../design/build-log/](../design/build-log/) for the
day-by-day notes.
