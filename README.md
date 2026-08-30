# NEXUS

A desktop tool that fixes bugs in a codebase and generates documents, running a
local LLM (via Ollama) on your own machine and only reaching for Claude when the
local model can't produce something that passes a real test.

The rule it's built around: **a model never approves its own work — a test does.**
Every change is built and checked on a throwaway copy of your folder and only
written back if the test passes.

## How this was built

I wrote the spec and a per-stage plan, then drove Claude Code through it over about
three days, reviewing each diff and using the test suite as the gate. So "built"
here means *designed, wired, and passing its tests* — not hand-written line by line,
and not yet hardened by real-world use. The [`design/build-log/`](design/build-log/)
folder is the honest day-by-day record; [`design/STATUS.md`](design/STATUS.md) is
the plain accounting of what's solid versus still a stub.

## What it does

- Fix a failing test in an existing **Python** project — make it pass, applied only
  if the fix verifies.
- Multi-file bug fixes in a real Python repo — it traces dependencies and makes a
  minimal change.
- Write a small new Python module plus its test from a prompt.
- Follow-up edits in the same folder ("now also handle the empty case").
- Fix **Kotlin/Java logic** bugs in a Gradle project *that already has JVM unit tests*.
- Answer questions about a codebase without changing anything.
- Generate **Word, PowerPoint, PDF, or Markdown** documents — themed, multi-section,
  written straight to your folder; optionally grounded on a file you attach.
- Describe attached images; load attached docs into a small knowledge base.
- Call tools from a project's `.mcp.json` (it's a generic MCP client).
- Run without git, escalate to Claude automatically, and stop a run mid-flight.
- Show a per-run cost line: fully local, or "N cloud calls, ~X tokens".

## What it doesn't do

- **Scaffold a new project.** It edits files; it doesn't create app/service/library
  skeletons from nothing.
- **Build or run an Android APK.** No Android SDK — Android "verification" is JVM
  unit tests only. No Compose/UI work, no iOS, no web frontend.
- **Game engines** — no Godot/Unreal, no scenes, levels, assets, or gameplay. (An
  engine-adapter layer was built and then removed; it wasn't worth the complexity.)
- **Anything visual, spatial, or creative** from a prompt — UI design, 3D, shaders,
  level design.
- **Verify without a test.** No pytest/Gradle test means it won't apply the change.
- **Instrumented / browser / e2e tests**, or large architectural rewrites.
- **Deploy, push, or open a PR** — local commits and branches only, by design.
- **Be fast** — roughly 40 s per reasoning step on an 8 GB GPU. One run at a time.

**Who it's for:** you have an existing Python (or Kotlin-with-unit-tests) codebase
and a steady trickle of small, test-backed fixes you'd rather not babysit in a chat
window. For building things, or anything visual, use Claude or an IDE assistant
directly — this isn't that.

![demo](docs/demo.gif)

*A real run: local `qwen3:8b` interprets, plans, and edits; its diff fails
verification; the orchestrator escalates to Claude; that diff passes in the Docker
sandbox; the fix is written back. Rebuild the GIF with `python docs/make_demo.py`.*

## How it works

Local LLMs (through Ollama) do the interpreting, planning, and first-pass editing.
The parts that decide anything — routing, the policy checks, hardware limits, the
progress/loop detector, and verification — are plain deterministic code, not model
calls. When a local diff fails its test or a run stalls, the same task is handed to
Claude (via the `claude` CLI's subscription session, not the paid API). Nothing is
written back until a verification passes.

- Code: [`nexus/`](nexus/)
- The thinking: [`design/`](design/) — [`overview.md`](design/overview.md),
  [`STATUS.md`](design/STATUS.md), [`requirements.md`](design/requirements.md),
  [`design-notes.md`](design/design-notes.md)
- Benchmarks: [`design/build-log/BUILDER_BENCH.md`](design/build-log/BUILDER_BENCH.md),
  [`design/build-log/LOCAL_FIRST_BENCH_REAL.md`](design/build-log/LOCAL_FIRST_BENCH_REAL.md)

## Setup

All commands run from `nexus/`.

**Python** (required, 3.12+):

```bash
cd nexus
python -m pip install -e .                 # base: pydantic only
python -m pip install -e ".[llm]"          # + anthropic + claude-agent-sdk
python -m pip install -e ".[postgres]"     # + psycopg (durable event store; optional)
```

**Docker** (for real verification): the verifier runs the target tests inside a
container. Build the image once:

```bash
docker build -t slice-sandbox:pytest app/services/sandbox/images/pytest-runner
```

Without Docker it falls back to a subprocess runner — fine for development, not
isolation.

**Claude** (subscription, no per-token cost): the default provider uses the `claude`
CLI's OAuth session.

```bash
claude          # log in once; the tool then reuses that session
```

Set `SLICE_LLM=anthropic` + `ANTHROPIC_API_KEY` in `nexus/.env.local` to use the
billed Messages API instead.

**Ollama** (local models):

```bash
winget install Ollama.Ollama                  # or https://ollama.com
ollama pull qwen3:8b                           # interpret / plan / critic / builder
ollama pull qwen2.5-coder:7b-instruct-q5_K_M   # optional: used as the builder model if present
ollama pull llava                              # optional: only for deck images (NEXUS_DECK_IMAGES=1)
```

`qwen3:8b` (~5 GB Q4) fits an 8 GB GPU with room for context and drives every role
by default. If a `qwen2.5-coder` model is present it's used as the builder only;
everything else stays on `qwen3:8b`, and it falls back to `qwen3:8b` if absent.

**Postgres** (optional durable store):

```bash
docker run -d --name nexus-pg -e POSTGRES_PASSWORD=nexus -e POSTGRES_USER=nexus \
  -e POSTGRES_DB=nexus -p 5433:5432 postgres:17-alpine
```

Then pass `--db postgres://nexus:nexus@localhost:5433/nexus` (or set `NEXUS_DB_URL`).
SQLite is the zero-dependency default.

**Desktop app** (optional): needs Node 18+, Rust (`rustup`), the platform C++
toolchain, and PyInstaller.

```bash
python -m pip install pyinstaller
python desktop/build.py
```

Produces installers under `desktop/src-tauri/target/release/bundle/`. On Windows
that's `NEXUS_0.1.0_x64-setup.exe` (NSIS) + `.msi` (WiX), each bundling the Tauri
shell and the frozen `nexus-server` sidecar. Windows-only so far; launch-verified.

## Run it

```bash
# offline sanity
python -m pytest tests/
python -m app.cli.demo                     # scripted end-to-end, no network

# a real task — local first, cloud only if it fails verification
python -m app.cli.run_task "Fix the off-by-one in paginate()." \
  --workspace /path/to/repo --full --apply

# local plan, cloud builder (fastest reliable mix)
python -m app.cli.run_task "<request>" --workspace <repo> --local --apply

# desktop shell
python -m app.ui.run_ui --db nexus.db --port 8770     # -> http://127.0.0.1:8770
```

`--full` wires the whole roster: interpreter, planner, a brainstorm pass,
local-first builder + cloud fallback, critic, an independent second verifier (on
cloud), the model router, memory/experience tracking, the tool-adapter registry,
and a per-changed-file policy check. `--apply` writes the diff back only on a
completed run with a passing verification.

## Benchmarks

Every model runs through the real builder loop (Ollama tool-calling:
`read_file` / `write_file` / `edit_file` / `run_tests` / `finish`), and every diff
is independently re-applied to a clean checkout and re-tested. `fixed` = the
harness verified it, not the model's self-report.

**Local builder, 10 seeded one-line bugs** (`design/build-log/BUILDER_BENCH.md`):

| model | fixed | tool-calls valid | avg turns | avg wall | avg tokens |
|---|---|---|---|---|---|
| qwen3:8b | 9 / 10 | 1.00 | 6.9 | 6.8 s | 8.4 k |
| qwen2.5-coder:7b | 6 / 10 | 0.97 | 11.9 | 16.3 s | 21 k |
| llama3.1:8b | 2 / 10 | 0.99 | 17.2 | 55.9 s | 27 k |

On this bench the general model beat the coding-specialist, which is why `qwen3:8b`
is the default. A larger coder tag (`:14b`) does better than the `:7b` here.

**End-to-end, real library bugs** (`design/build-log/LOCAL_FIRST_BENCH_REAL.md`):
5 actual `more-itertools` fix commits (source reverted, test kept), run through the
full pipeline:

| | seeded one-liners | real library bugs |
|---|---|---|
| solved locally (no cloud) | 8–10 / 10 | 1 / 5 |
| solved after escalation to cloud | 0–2 / 10 | 3 / 5 |
| failed | 0 | 1 / 5 (failed *safe* — cloud verifier dissented → waited for the user) |
| end-to-end success | 10 / 10 | 4 / 5 |
| time per task | 12–26 s | 2–6 min |

So: a local 8B model on an 8 GB GPU fixes ~20% of genuine bugs on its own; the
local-first-then-escalate path takes that to ~80%, and the miss failed safe rather
than shipping a bad diff. These numbers are from my runs — if you're relying on
them, reproduce the benchmark yourself from a clean checkout.

**Test suite:** 523 tests, offline and deterministic, `pydantic` the only base
dependency. `python -m pytest tests/` from `nexus/`.

## License

© 2026 Mohammed Salem Sayed. [PolyForm Noncommercial License 1.0.0](LICENSE)
(see also [`NOTICE`](NOTICE)).

- Use, modify, and redistribute it — including your own forks and derivative
  versions — for any **noncommercial** purpose.
- Keep the `LICENSE` and `NOTICE` files with any copy, and credit the original
  author.
- **Any commercial or business use needs a separate written license.** Contact
  **mohammed.salem.sayed@gmail.com**.

Source-available, not an OSI-approved open-source license. Bundled dependencies
keep their own licenses.
