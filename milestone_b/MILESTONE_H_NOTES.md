# Milestone H notes — what is real, what remains

Status against [../MILESTONE_H_PLAN.md](../MILESTONE_H_PLAN.md) and
[../MILESTONE_H_TAURI_PLAN.md](../MILESTONE_H_TAURI_PLAN.md). **314 tests green.**
The shell (14 days) plus the Tauri packaging scaffold are built.

## Real after Milestone H

| Area | Module | Notes |
|---|---|---|
| Read models | `app/ui/readmodels.py` | Six pure folds of the event log: `task_list()`, `task_timeline(task_id)` (ordered rows + state transitions + spend rollup + verification), `agents_panel(task_id)` (latest `AgentMessage` per role, 8 roles), `system_health(task_ids)` (latest `HARDWARE` mode, budget posture, active/rolled-back canaries, quarantine count), `metrics_panel()` (wraps the Milestone I `rebuild_metrics`), `routes_panel()` (recent `ROUTE` decisions + per-class provider tallies). No state; same log → same output. A `_HEADLINES` map covers every event kind; an unmapped kind degrades to a generic row, never an error. |
| Event feed | `app/ui/events.py` | `EventFeed(log, task_id=, since_seq=)` tails the append-only `events` table by `seq > cursor` (monotonic — a poll is correct). `poll()` advances the cursor past filtered-out rows too. `sse_frame(event)` / `keepalive_frame()` format Server-Sent-Events frames. |
| HTTP + SSE server | `app/ui/server.py` | stdlib `http.server.ThreadingHTTPServer`, binds **127.0.0.1** only, no auth (single-user, loopback). `GET /api/health`, `/api/tasks`, `/api/tasks/{id}`, `/api/tasks/{id}/agents`, `/api/system`, `/api/metrics`, `/api/routes`; `GET /api/stream` (SSE, optional `?task_id=` / `?since=`; default tails from the current max seq); `GET /` + `/app.js` + `/style.css` (path-escape guarded). Opens a fresh `EventLog` per request (SQLite thread-safety); the stream keeps one open for the connection. Unknown routes → 404; a bad `task_id` → 404, not 500. |
| Task submit (opt-in) | `POST /api/tasks` | `{request, workspace}`. Returns **405** unless the server was constructed with a `runner` callback (`run_ui.py --allow-submit`). The callback is a real `Orchestrator.run` — every policy / capability / approval / budget gate still applies; the UI initiates nothing the CLI could not. |
| Frontend | `app/ui/web/{index.html,app.js,style.css}` | One self-contained page, **no build step**, vanilla JS. Subscribes to `/api/stream` via `EventSource`, debounce-refreshes the panels on relevant events, reconnects on drop. Renders: task list, conversation/timeline (headline + detail + state rows), agents panel, system-health strip, metrics panel, routing tallies, and a submit box. Replaces the prior static `apps/desktop/src/App.tsx` mock with a real client. Verified live against a 3-task seeded DB. |
| Entrypoint | `app/ui/run_ui.py` | `python -m app.ui.run_ui --db <event.db> [--port 8770] [--allow-submit]`. Serves an existing event-log DB; `--allow-submit` also builds an `Orchestrator` over it (Agent SDK / subscription) and wires the POST route. |
| Events | none — H only reads the log. |

## Tauri packaging (MILESTONE_H_TAURI_PLAN.md) — scaffolded

| Piece | Module | Notes |
|---|---|---|
| Frozen-aware paths | `app/ui/paths.py` | `web_dir()` resolves the frontend from source or a PyInstaller bundle (`sys._MEIPASS`); `default_db_path()` → `<per-user data dir>/nexus/events.db`. `server.py` now uses `web_dir()`. |
| Sidecar entrypoint | `app/ui/sidecar_main.py` | what PyInstaller freezes into `nexus-server` and Tauri spawns. Same `app.ui.server`, defaults tuned for a frozen app: per-user DB, `NEXUS_PORT`, submit off unless `NEXUS_ALLOW_SUBMIT=1`. Covered by `tests/integration/test_sidecar.py` (runs it as a real subprocess). |
| Tauri v2 project | `desktop/src-tauri/` | `Cargo.toml`, `tauri.conf.json` (identifier, window `main` on `splash.html`, `bundle.externalBin` = `binaries/nexus-server`, NSIS/MSI/dmg/deb/appimage targets), `build.rs`, `capabilities/default.json` (shell-execute scoped **only** to the sidecar). |
| Rust shell | `desktop/src-tauri/src/main.rs` | `setup()`: resolve app-data dir → spawn `nexus-server` sidecar with `--db`/`--port` → drain its output to the log → background thread TCP-polls the port (~18 s) then `window.navigate("http://127.0.0.1:8770")`, else stays on `splash.html`. `run()`: `RunEvent::ExitRequested` → `child.kill()`. |
| Build | `desktop/build_sidecar.py` (PyInstaller → `src-tauri/binaries/nexus-server-<triple>`), `desktop/build.py` (one command: sidecar → `npm ci` → `npm run tauri build`; fails fast with a named missing prerequisite), `desktop/gen_icons.py` (Pillow → committed icon set + `.ico`). |
| Frontend dist | `desktop/dist/splash.html` — "starting the control plane…" until the sidecar is up. |

**Not `cargo build`-verified here** — this environment has no Rust toolchain, no
PyInstaller, no global npm packages. `desktop/build.py` correctly exits 2 with the missing
prerequisites (asserted in `test_sidecar.py::test_build_script_reports_missing_toolchain`).
The Rust source is written to the Tauri v2 API; the Python half (paths, sidecar, config
shape) is tested. Producing a signed installer is `install Rust + PyInstaller + platform
build tools → python desktop/build.py`, plus code-signing certs — the same "needs an external
resource" boundary as the premise test / benchmark / model seeder / guardrail runner.

## Not yet real / deferred

- **Native binary not produced here** — the scaffold above is complete; a build host with
  the toolchain runs `python desktop/build.py`. Code signing, auto-update, tray, and a
  single-instance guard are additive and deferred (see `desktop/README.md`).
- **No framework / component library** — the frontend is one hand-written page. It streams,
  renders every panel, and reconnects (the milestone's point); a React/Vite rewrite is
  cosmetic and additive, and would consume the same endpoints unchanged.
- **SSE poll, not push** — the stream polls the append-only table every 250 ms. Correct and
  cheap for one local user; a push notifier (SQLite update hook, or an in-process queue when
  the server and orchestrator share a process) is a later optimization.
- **WebSocket** — not needed; SSE covers server→client streaming, which is all the panels
  require. Bidirectional WS only if a future interactive panel needs it.
- **Panels still to build** — live artifact diff viewer, the research evidence graph, an
  experience-repository browser. The read-model pattern extends to each without touching the
  server (add a fold + a route).
- **Submit path is minimal** — `POST /api/tasks` runs synchronously and returns the
  `TaskResult`; a long task blocks that one request thread (others are unaffected). An async
  job model belongs with the push notifier work.

## Deferred past H (unchanged)

Tauri packaging + native shell integration; embedding / vector retrieval — CD-rag; local
model backend adapters — capability-domain work (§10.2); logistic-regression routing-weight
fit — Milestone I follow-up (needs a real run corpus); multi-user / remote access — never
(single-user non-goal).
