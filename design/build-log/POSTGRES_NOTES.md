# Postgres event store — durable multi-session persistence

The `EventLog` seam (design-notes §1, MILESTONE_A) always anticipated moving
off SQLite. This wires the alternative without touching the ~60 call sites.

## What's real

| Piece | File |
|---|---|
| `PostgresEventLog` | `app/events/pg_log.py` — identical interface to `EventLog` (`append` / `read` / `all` / `task_ids` / `close` / context manager), `psycopg` v3, `JSONB` payload, `BIGSERIAL` seq, `INSERT … RETURNING seq`, append-only (no UPDATE/DELETE). Schema created on first connect. |
| `open_event_log(target)` | `app/events/log.py` — factory: `postgres://` / `postgresql://` → `PostgresEventLog`; `sqlite:///path` / a bare path / `:memory:` → `EventLog`. `NEXUS_DB_URL` env var overrides. |
| Entrypoints | `app/cli/run_task.py` (`--db`), `app/ui/run_ui.py`, `app/ui/server.py` all go through `open_event_log`. |
| Dependency | `pyproject.toml` optional extra `postgres = ["psycopg[binary]>=3.2"]`. SQLite stays the default with **zero** extra deps. |
| Tests | `tests/integration/test_pg_event_log.py` — 6 cases (factory dispatch, append/read/all/task_ids parity, pydantic-model payload, bad-payload TypeError, **durable across reconnect**, projection fold over a Postgres stream). Skipped unless `NEXUS_PG_TEST_DSN` is set. |

## Verified

- 6/6 Postgres tests green against `postgres:17-alpine` (Docker, `localhost:5433`).
- A full real task end to end:
  `run_task "fix slugify…" --local --apply --db postgres://nexus:nexus@localhost:5433/nexus`
  → local `qwen3:8b` interpret+plan, cloud Builder, Docker T0 verify → `COMPLETED`
  → **25 events persisted in Postgres** (`REQUEST, STATE, CONTRACT, MODEL_RUN,
  AGENT_MESSAGE, …`), survive process exit.
- Full SQLite regression unchanged (the default path).

## Run it

```bash
docker run -d --name nexus-pg -e POSTGRES_PASSWORD=nexus -e POSTGRES_USER=nexus \
  -e POSTGRES_DB=nexus -p 5433:5432 postgres:17-alpine
pip install "psycopg[binary]>=3.2"          # or: pip install -e ".[postgres]"

python -m app.cli.run_task "<request>" --workspace <repo> --full \
  --db postgres://nexus:nexus@localhost:5433/nexus
# or export NEXUS_DB_URL=postgres://… and drop --db
```

## Not done / next

- **Migrations.** Schema is `CREATE TABLE IF NOT EXISTS`. A real Alembic (or
  sqlite→pg copy) migration is a drop-in behind `open_event_log`; no caller changes.
- **Connection pooling.** One connection per `PostgresEventLog` (autocommit). The
  UI server opens one per request (same as the SQLite path). A `psycopg_pool`
  pool is the obvious upgrade for a multi-client deployment.
- **The other stores** (`MemoryStore`, `ExperienceStore`, `RouteStatsStore`) are
  still SQLite — they have their own seams; port them the same way if/when a
  deployment needs shared memory across processes.
