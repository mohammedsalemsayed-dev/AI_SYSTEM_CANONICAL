# Milestone H notes — what is real, what remains

Status against [../MILESTONE_H_PLAN.md](../MILESTONE_H_PLAN.md). **306 tests green.**
All 14 days built.

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

## Not yet real / deferred

- **Not a native app** — H ships a served page, not a Tauri binary. Wrapping `app/ui/web/`
  in a Tauri (or Electron) shell — native window, tray, auto-update — is a packaging step on
  top of the exact same page and the exact same API. Called out, not silently dropped.
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
