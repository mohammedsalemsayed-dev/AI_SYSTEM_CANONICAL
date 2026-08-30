# Milestone H — Desktop Shell Plan


---

## 1. Purpose

Everything B–I produces is in the event log and nothing renders it. The prior-foundation
`apps/desktop/src/App.tsx` is a static mock with no data wiring; `apps/backend` is two health
routes. Milestone H builds the real shell:

- an **event-stream API** — a small dependency-free HTTP + SSE server over the existing
  append-only SQLite event log;
- the **read models** — pure folds of the log into exactly the views §11.2 names: the
  per-task timeline (states / actions / evidence / spend), per-model rolling stats, the
  system-health strip, and the metric set (success rate by `task_class`, rework rate,
  verify-tier distribution, escalation frequency, budget-exhaustion rate, quarantine
  events);
- a **wired frontend** — a single self-contained page that subscribes to the stream and
  renders the conversation, the agents panel, the health strip, and the metrics, replacing
  the static mock with a real client.

Guiding rules:
- **§11.2** — every view is *derived*; the read models are pure functions over the event
  log and hold no state of their own. If a view and the log disagree, the log wins.
- **D6 / append-only** — the API is **read-only** over history; it never mutates or deletes
  events. Task submission (if wired) goes through the orchestrator like any other run.
- **Non-goal (unchanged)** — no autonomous side effects: a submitted task still hits every
  policy / approval gate; the UI initiates nothing the CLI could not.
- **Dependency discipline** — the slice depends only on `pydantic`. H adds no runtime
  dependency: the server is stdlib `http.server`, the frontend is one vanilla-JS page with
  no build step. Tauri packaging is a documented final step, not a slice dependency.

## 2. In scope

| Concern | Milestone H implementation |
|---|---|
| Read models | `app/ui/readmodels.py`: pure functions over `EventLog` → JSON-able dicts. `task_list()`, `task_timeline(task_id)`, `agents_panel(task_id)`, `system_health(task_ids)`, `metrics_panel(task_ids)` (wraps Milestone I `rebuild_metrics`), `routes_panel(task_ids)`. Every headline/detail derived from the event payloads already logged. |
| Event feed | `app/ui/events.py`: `EventFeed` tails the `events` table by `seq > last_seq` (append-only, monotonic — a poll is correct and cheap). `sse_frame(event)` formats one Server-Sent-Events frame. Optional `task_id` filter. |
| HTTP + SSE server | `app/ui/server.py`: `http.server.ThreadingHTTPServer` + a router. `GET /api/health`, `/api/tasks`, `/api/tasks/{id}`, `/api/tasks/{id}/agents`, `/api/system`, `/api/metrics`, `/api/routes`, `/api/stream` (SSE; optional `?task_id=`), `GET /` + `/app.js` (static frontend). JSON bodies, CORS off (localhost only), no auth (single-user, loopback bind). |
| Task submit (opt-in) | `POST /api/tasks {request, workspace}` is wired **only** when the server is constructed with a `runner` callback; default build is read-only and returns 405. The callback is the caller's `Orchestrator.run` — every policy / approval / budget gate still applies. |
| Frontend | `app/ui/web/index.html` + `app.js` + `style.css`: one self-contained page (no bundler). Subscribes to `/api/stream`, renders: the conversation/timeline column, the agents panel (per-role latest `AgentMessage` / status), the system-health strip (hardware mode, budget posture, active canaries, quarantine count), and the metrics panel. Replaces the prior static mock. |
| Entrypoint | `app/ui/run_ui.py`: `python -m app.ui.run_ui --db <event.db> --port 8770 [--allow-submit]`. Serves an existing event-log DB. |
| Events | none new — H only reads. |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Tauri packaging (native window, updater, tray) | a packaging step on top of the served page — documented, not built here |
| A React/Vite build with a component library | the slice ships one vanilla-JS page; a framework rewrite is cosmetic and additive |
| WebSocket (bidirectional) | SSE covers server→client streaming, which is all the panels need; WS only if a future interactive panel requires it |
| Auth / multi-user / remote access | never (single-user, loopback-only, D non-goal) |
| Live artifact diff viewer, research evidence graph UI | later panels — the read-model pattern extends to them without server changes |

## 4. Component layout

```
app/ui/
  readmodels.py   task_list / task_timeline / agents_panel / system_health /
                  metrics_panel / routes_panel — pure folds over EventLog
  events.py       EventFeed (tail by seq) + sse_frame()
  server.py       ThreadingHTTPServer + Handler; GET routes + SSE + static; opt-in POST
  run_ui.py       CLI entrypoint
  web/index.html  the shell
  web/app.js      stream subscription + rendering
  web/style.css
app/services/eval/metrics.py   reused by metrics_panel (no change)
tests/
  unit/         test_ui_readmodels, test_ui_eventfeed
  integration/  test_ui_server  (real socket: GETs + an SSE read; opt-in submit)
```

## 5. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–3 | `app/ui/readmodels.py` — all six folds + their JSON shapes. Unit tests over hand-built logs: a completed task's timeline has ordered state transitions + spend; `agents_panel` shows the last message per role; `system_health` reflects a logged `HARDWARE` / `BUDGET` / `CANARY`. |
| 4–5 | `app/ui/events.py` — `EventFeed` tail-by-seq, resume from `last_seq`, optional `task_id` filter; `sse_frame()`. Unit tests: feed yields only new rows, survives an empty poll, formats a valid frame. |
| 6–8 | `app/ui/server.py` — `ThreadingHTTPServer` + router for every `GET /api/*` route returning the read models as JSON; `GET /` + static assets. Integration test on an ephemeral port: each route returns the expected shape for a seeded DB. |
| 9–10 | `/api/stream` SSE endpoint wired to `EventFeed` (chunked, `text/event-stream`, keep-alive comments). Integration test: connect, append 2 events, read 2 frames. `run_ui.py` entrypoint. |
| 11–12 | `web/index.html` + `app.js` + `style.css` — subscribe to the stream, render the four panels, reconnect on drop. Smoke test: `GET /` serves HTML that references `/api/stream` and `/app.js`; `GET /app.js` serves JS. |
| 13 | Opt-in `POST /api/tasks` behind an injected `runner` callback (read-only by default → 405); `--allow-submit` flag. Integration test with a fake runner: a POST runs it and the new task appears in `/api/tasks`. |
| 14 | Regression; `../nexus/MILESTONE_H_NOTES.md`; update [STATUS.md](../STATUS.md) + the [connective index](../requirements.md); . |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — each read model is a pure function of the event list (same log → same output,
  no wall-clock dependence beyond event `ts`); `task_timeline` orders by `seq` and includes
  every state transition + the spend rollup; `agents_panel` returns the latest message per
  role and nothing for a role that never spoke; `system_health` reports the most recent
  `HARDWARE` mode, budget posture, live-canary count, and quarantine count; `EventFeed`
  resumes strictly after `last_seq` and never re-emits.
- **Integration** — with a seeded event-log DB, every `GET /api/*` route returns HTTP 200
  and the documented JSON shape; `/api/stream` delivers a frame per event appended after the
  connection opens; `GET /` and `/app.js` serve the assets; unknown routes return 404.
- **Failure** — a malformed `task_id` returns 404, not a 500; a dropped SSE client does not
  crash the server or block other requests (threaded).
- **Security** — the server binds loopback only; `POST /api/tasks` returns 405 unless
  `--allow-submit` wired a runner; a submitted task still passes through policy / approval
  (the UI cannot bypass a gate); no route mutates or deletes an event.
- **Recovery** — pointing `run_ui.py` at a DB from an interrupted run renders the partial
  timeline without error; the server holds no state that a restart loses.
- **Benchmark** — n/a (H adds no model calls).

## 7. Tunable starting values

- SSE poll interval: **250 ms** (loopback, single user — latency over CPU).
- Keep-alive comment: every **15 s**.
- Default port: **8770**; bind **127.0.0.1** only.
- `task_list` / timeline page size: **200** most-recent (matches §11.3 relevance-bounded
  retrieval, not deletion).

## 8. Risks

- **Not a native app** — H ships a served page, not a Tauri binary. That is deliberate for
  the slice (no toolchain dependency, verifiable with pytest); the Tauri wrapper is a
  packaging task over the same page and is called out, not silently dropped.
- **SSE poll vs. push** — polling the append-only table every 250 ms is simple and correct
  for one local user; a push notifier (SQLite `sqlite3_update_hook` via a wrapper, or a
  process-internal queue) is a later optimization if the event rate ever makes polling hurt.
- **Read-model drift** — if a headline mapping falls behind a new event kind, that event
  shows as a generic row, never an error. New kinds get a headline in the same PR that adds
  them going forward.
- **Frontend minimalism** — one vanilla page will not win design awards; it is a *real*
  client (streams, renders every panel, reconnects), which is the milestone's point. A
  framework pass is additive.

## 9. Deliverables

- `app/ui/readmodels.py` (six §11.2 folds), `app/ui/events.py` (`EventFeed` + SSE),
  `app/ui/server.py` (stdlib HTTP + SSE + static, opt-in submit), `app/ui/run_ui.py`.
- `app/ui/web/` — a self-contained wired shell (conversation + agents + health strip +
  metrics), replacing the prior static mock.
- Test suite: the current 290 green, plus unit (read models / event feed) and integration
  (server routes + a real SSE read + opt-in submit).
- `../nexus/MILESTONE_H_NOTES.md`.
- [STATUS.md](../STATUS.md) and the
  [connective index](../requirements.md) updated:
  "Futuristic desktop UI" and "WebSocket / event streaming" move toward FOUNDATION (with the
  Tauri wrapper noted as the remaining packaging step).
