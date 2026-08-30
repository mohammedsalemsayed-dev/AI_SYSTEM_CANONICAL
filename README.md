# NEXUS — a local, verify-first code fixer + document generator

A desktop app that runs an autonomous agent **on your own machine** using local LLMs
(via Ollama), escalating to Claude (Sonnet/Opus via your Claude subscription — not paid
API) only when the local model can't produce something that **passes a real test**.

Design principle: **LLMs propose, deterministic components decide.** A model never
approves its own work — a test does. Every change is built and verified on a throwaway
copy of your folder and only written back if the test passes.

## What it actually does — and doesn't

**This is a narrow tool.** It does one thing well: local, credit-free, *verified* code
fixes on testable projects, unattended — plus document generation. It is **not** a
"build me an app / game / thing" tool.

### It CAN

- **Fix a failing test** in an existing **Python** project → make it pass, applied only if verified
- **Multi-file bug fixes** in a real Python repo — traces dependencies, makes a minimal change
- **Write a small new Python module + its test** from a prompt
- **Follow-up edits** threaded in the same folder ("now also add …")
- Fix **Kotlin/Java logic** bugs in an existing Gradle project **that has JVM unit tests**
- **Answer questions** about a codebase without changing anything
- **Generate documents** — Word (`.docx`), PowerPoint (`.pptx`), PDF, Markdown — themed,
  multi-section, writes the file to your folder; optionally **grounded on an attached file**
- **Describe attached images**; ingest attached docs into a knowledge base
- Call tools from a project's **`.mcp.json`** (generic MCP client)
- Run **without git**, in any folder; **escalate to Claude** automatically; **Stop** a run mid-flight
- **Cost line** shows "100% local" vs "☁ N cloud calls · ~X tok" per run

### It CAN'T

- **Scaffold a new project** from nothing (app, service, library, CLI) — it edits files, not skeletons
- **Build / run an Android APK** — no Android SDK; Android verification is JVM unit tests only
- **Android UI / Compose / layouts**, **iOS**, or **web frontend with visual verification**
- **Godot / Unreal / any game engine** — no scene, level, asset, or gameplay work
- **Level / environment / game design**, **3D / graphics / shaders**, **visual / UI design**
- **Verify anything without a test** — no pytest/Gradle test = it won't apply the change
- **Instrumented / UI / e2e / browser tests**; **large architectural rewrites**
- **Deploy, push to a remote, open a PR** — blocked by design (local commits/branches only)
- Hard algorithm problems on the **local model alone** (it escalates; cloud then can)
- **Fast** responses — ~40 s per reasoning step on a typical 8 GB GPU
- **Concurrent runs** (one at a time); meaningfully edit **binary files**
- Anything **creative, visual, or spatial** from a prompt

**Who it's for:** you have an existing Python (or Kotlin-with-unit-tests) codebase and a
stream of small, test-backed fixes you want done for free without babysitting a chat. For
building things, or anything visual/creative, use Claude or an IDE assistant directly.

---

## Architecture (the enforced part)

Specialised LLM agents propose and reason; **deterministic services enforce** — state,
permissions, execution boundaries, verification, recovery, memory trust, controlled
learning, hardware protection, and model routing.

The loop: **run the work on a local model when it can, escalate to a cloud model when
it can't — automatically, and never ship an unverified change.**

![demo](docs/demo.gif)

*A real `run_task --full` run: local `qwen3:8b` interprets, plans (with a Creative-agent
brainstorm) and edits; its diff **fails T0 verification**; the orchestrator **auto-escalates
to cloud Claude**; that diff **passes in the Docker sandbox**; the task completes verified
and the fix is written back. Rebuild the GIF with `python docs/make_demo.py`.*

- Running code: [`milestone_b/`](milestone_b/) — the live build.
- Design package: [`DESIGN_TIGHTENING.md`](DESIGN_TIGHTENING.md) (§13 is the map),
  [`02_CONTEXT_AND_TRACEABILITY/`](02_CONTEXT_AND_TRACEABILITY/) (requirement → milestone → status).
- Honest boundary: [`02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md`](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md).
- Real-run findings: [`milestone_b/REAL_RUN_FINDINGS.md`](milestone_b/REAL_RUN_FINDINGS.md),
  [`milestone_b/BUILDER_BENCH.md`](milestone_b/BUILDER_BENCH.md),
  [`milestone_b/LOCAL_FIRST_BENCH_REAL.md`](milestone_b/LOCAL_FIRST_BENCH_REAL.md),
  [`milestone_b/POSTGRES_NOTES.md`](milestone_b/POSTGRES_NOTES.md).

---

## Setup

All commands run from `milestone_b/`.

### 1. Python (required)

```bash
cd milestone_b
python -m pip install -e .                 # base: pydantic only
python -m pip install -e ".[llm]"          # + anthropic + claude-agent-sdk (real Claude)
python -m pip install -e ".[postgres]"     # + psycopg (durable event store; optional)
```

Runs on Python 3.12+. The offline test suite needs nothing but `pydantic`.

### 2. Docker (for real verification)

`VerifierT0` runs the target tests inside a sandbox container. Build the image once:

```bash
docker build -t slice-sandbox:pytest app/services/sandbox/images/pytest-runner
```

Without Docker the suite falls back to a subprocess runner (not isolation — dev only).

### 3. Cloud model (subscription, no per-token spend)

The default `agent_sdk` provider uses the `claude` CLI's OAuth session:

```bash
claude          # run once to log in; then the system uses it, no API key
```

Set `SLICE_LLM=anthropic` + `ANTHROPIC_API_KEY` in `milestone_b/.env.local` to use the
billed Messages API instead.

### 4. Local models (Ollama)

```bash
winget install Ollama.Ollama            # or https://ollama.com
ollama pull qwen3:8b                          # general: interpret / plan / critic / builder
ollama pull qwen2.5-coder:7b-instruct-q5_K_M  # optional: used as the builder model if present
ollama pull llava                            # optional: only for deck auto-visuals (NEXUS_DECK_IMAGES=1)
```

`qwen3:8b` (~5 GB Q4) fits an 8 GB GPU with room for context and drives every role by
default. If a `qwen2.5-coder` model is pulled, `app/ui/runner.py` uses it as the *builder*
model only (interpret/plan/critic stay on `qwen3:8b`); nothing else changes and it falls
back to `qwen3:8b` when absent. See the benchmark below.

### 5. Postgres (optional — durable, multi-session store)

```bash
docker run -d --name nexus-pg -e POSTGRES_PASSWORD=nexus -e POSTGRES_USER=nexus \
  -e POSTGRES_DB=nexus -p 5433:5432 postgres:17-alpine
```

Then pass `--db postgres://nexus:nexus@localhost:5433/nexus` (or set `NEXUS_DB_URL`).
SQLite is the zero-dependency default.

### 6. Desktop app (optional)

Needs Node 18+, Rust (`rustup`), and the platform toolchain (Windows: MSVC "Desktop
development with C++"; macOS: Xcode CLT; Linux: `webkit2gtk-4.1` et al.), plus PyInstaller.

```bash
python -m pip install pyinstaller
python desktop/build.py
```

Produces installers under `desktop/src-tauri/target/release/bundle/`. On this repo's Windows
host that yields `NEXUS_0.1.0_x64-setup.exe` (NSIS) + `.msi` (WiX), each bundling the Tauri
shell plus the frozen `nexus-server` control-plane sidecar. Launch-verified.

---

## Run it

### Offline sanity

```bash
python -m pytest tests/unit tests/security tests/integration tests/regression tests/fault
python -m app.cli.demo                     # scripted end-to-end, no network
```

### A real task

```bash
# fully local: qwen3:8b interprets, plans, edits; cloud only if it fails verification
python -m app.cli.run_task "Fix the off-by-one in paginate()." \
  --workspace /path/to/repo --full --apply

# local plan, cloud builder (fastest reliable mix)
python -m app.cli.run_task "<request>" --workspace <repo> --local --apply
```

`--full` wires the complete roster: Interpreter, Planner, **Creative/Brainstorm agent**,
local-first Builder + cloud fallback, Critic, independent T2 verifier (on cloud), Router +
provider registry, memory / experience / role-performance, the tool-adapter registry, and
the §14.1 per-file policy gate. `--apply` writes the verified diff back (only on
`COMPLETED` + a passing verification). `--db postgres://…` for durable storage.

The deterministic layers (Router, Hardware Scheduler, Policy Engine, Progress/Loop
Detector) never call an LLM and are always on.

### Desktop shell

```bash
python -m app.ui.run_ui --db slice.db --port 8770     # -> http://127.0.0.1:8770
```

---

## Benchmark results

Every model runs through the **real `LocalBuilder`** agentic loop (Ollama tool-calling:
`read_file` / `write_file` / `edit_file` / `run_tests` / `finish`); every diff is
independently re-applied to a clean checkout and re-tested. `fixed` = diffs the harness
verified, not the model's self-report.

### Local Builder — model comparison (`BUILDER_BENCH.md`, 10 seeded one-line bugs)

| model | fixed | tool-call valid | avg turns | avg wall | avg tokens |
|---|---|---|---|---|---|
| **qwen3:8b** | **9 / 10** | 1.00 | 6.9 | 6.8 s | 8.4 k |
| qwen2.5-coder:7b | 6 / 10 | 0.97 | 11.9 | 16.3 s | 21 k |
| llama3.1:8b | 2 / 10 | 0.99 | 17.2 | 55.9 s | 27 k |

On this bench the coding-specialist lost, so `qwen3:8b` is the default for every role.
A `qwen2.5-coder` model, if pulled, is still used as the *builder* model (opt-in, see
setup) — larger coder tags (`:14b`) do better than the `:7b` measured here. `llama3.1:8b`
emits valid tool syntax but can't drive the task (hits the turn cap 60 % of the time).

### End-to-end, full stack — real library bugs (`LOCAL_FIRST_BENCH_REAL.md`)

5 actual `more-itertools` fix commits (source reverted, test kept; `more.py` ≈ 4 000 lines),
run through the whole pipeline with local-first → cloud escalation:

| | one-line seeded bugs | **real library bugs** |
|---|---|---|
| solved on-device (local only) | 8–10 / 10 | **1 / 5** |
| solved after auto-escalation to cloud | 0–2 / 10 | 3 / 5 |
| failed | 0 | 1 / 5 (failed *safe* — cloud T2 dissent → `WAITING_FOR_USER`) |
| **end-to-end success** | 10 / 10 | **4 / 5** |
| time / task | 12–26 s | 2–6 min |

**The measured verdict:** a local 8 B model on an 8 GB GPU solves ≈ 20 % of genuine bugs
alone; the local-first → escalate architecture takes it to ≈ 80 %, and the last case fails
safe to a human instead of shipping a bad fix.

### Test suite

**523 tests** green (`milestone_b/tests/{unit,security,integration,regression,fault}`),
offline-deterministic, base dependency `pydantic` only. The 6 Postgres tests skip unless
`NEXUS_PG_TEST_DSN` is set. Run from `milestone_b/`: `python -m pytest tests/`.

---

## Build status

| Area | State |
|---|---|
| Milestones A–V (control plane + §10.2 capability domains + hardening) | **built** — see the table below |
| Real Claude integration (subscription / Agent SDK) | **built + verified** |
| Local models (Ollama: `OllamaLLM` interpret/plan, `LocalBuilder` agentic edit) | **built + benchmarked** |
| Local-first → cloud escalation on verification failure | **built + verified** |
| Full agent roster incl. Creative/Brainstorm agent | **built** (`run_task --full`) |
| PostgreSQL event store (`PostgresEventLog`, `--db postgres://…`) | **built + verified** |
| Native desktop installers (Tauri + PyInstaller sidecar) | **built** (Windows NSIS + MSI) |

Not done: Alembic migrations (schema is `CREATE IF NOT EXISTS`) + connection pooling;
the other stores (`MemoryStore` / `ExperienceStore` / `RouteStatsStore`) still on SQLite;
Redis/queue; a secrets vault; macOS/Linux bundles; T2-verifier false-positive tuning.

<details>
<summary>Milestone table (A–V)</summary>

| Milestone | Scope | Status |
|---|---|---|
| **A** Foundation | state machine, event log, contracts | scaffolded (prior foundation) |
| **B** Vertical slice | `request → contract → plan → edit → T0 verify → result` | **built** |
| **C** Security & authority | capability registry, scoped grants, 7-rule policy engine, sandbox tiers, approvals | **built** |
| **D** Recovery & progress | checkpoints, idempotency, reconciliation, 6 hard-progress signals, loop detector, escalation ladder | **built** |
| **E** Multi-agent | Critic (T0-first), independent T2 ensemble verifier, disagreement protocol, Researcher, composition rule | **built** |
| **F** Memory & experience | hierarchical memory, trust-filtered retrieval, full experience lifecycle, catastrophic rollback | **built** |
| **G** Routing & hardware | provider registry, static table + escalation triggers, data-driven blend, hardware modes + `EMERGENCY` pause | **built** |
| **I** Optimization | frozen guardrail suite, fail-closed regression gate, held-out `OfflineEval` gate, canary rollback | **built** |
| **H** Desktop shell | 6 read-model folds, loopback HTTP/JSON API, SSE stream, no-build frontend | **built** |
| **H** Tauri packaging | Tauri v2 native shell + PyInstaller sidecar + one-command build | **built** — Windows installers produced |
| **J** Repo intelligence & Git adapter | deterministic Git adapter, `ast` symbol index, dependency graph, blast-radius `ImpactReport` | **built** |
| **K** Research pipeline & evidence graph | decomposition, evidence graph, bounded cross-check, claims-only cited synthesis, injection scan | **built** |
| **L** RAG / knowledge base | ingest + heading-aware chunking + BM25 behind a `Retriever` protocol; `doc_analysis` flow | **built** |
| **M** Authoring pipelines | `DocumentModel` + `SlideDeck`; outline → grounded draft → review → render | **built** |
| **N** ~~Engine adapters & expert modes~~ | **REMOVED** — built, then removed in full (not worth the complexity). `AndroidVerifier` (a `gradlew` JVM-unit-test T0 gate) is all that remains, and it lives in the verifier layer, not an adapter. | removed |
| **O** Automated model selection | logistic-regression `WeightSet` fit + `ModelSelectionController`, regression-gated, canary-demoted | **built** |
| **P** Artifact & version tracking | content-addressed `ArtifactStore` + per-objective version chain + mark-never-delete | **built** |
| **Q** Fault injection & recovery hardening | fault wrappers + hard-kill hook; 20-case suite proving safe-terminal / clean-reconcile | **built** |
| **R** Telemetry & calibration | live `HardwareMonitor` (RAM/CPU/disk + `nvidia-smi`) + one-time `calibrate()` → budget scaling | **built** |
| **S** Tool adapter framework | `ToolAdapter` Protocol + `ToolRegistry` + `ToolDispatcher` through the existing Policy Engine | **built** |
| **T** Tool-use execution | `ShellToolAdapter` + bounded deterministic `ToolLoop`; `ops` is a first-class flow | **built** |
| **U** Loop detection for the tool loop | D's `LoopDetector` per turn → early `loop_risk` stop → escalate to the user | **built** |
| **V** Per-changed-file policy checks | `per_file_policy` re-runs the Policy Engine per touched file so the §14.1 risk-class gate actually fires | **built** |

</details>

---

## Non-negotiable rules

- LLMs propose and reason; deterministic components enforce. An LLM is never the final
  authority for permissions, verification, or hardware limits.
- Never ship a change that has not passed independent verification.
- `retrieved_web` / `doc_input` content can never originate a side effect, change the
  objective, or widen a capability (§12).
- "Foundation" / "seam" ≠ "complete" — deferred subsystems are present as named interfaces,
  never silently dropped.

---

## License

© 2026 **Mohammed Salem Sayed**. Licensed under the
[**PolyForm Noncommercial License 1.0.0**](LICENSE) (see also [`NOTICE`](NOTICE)).

- **You may** use, modify, and redistribute this project — including your own
  modified or derivative versions — for any **noncommercial** purpose.
- **You must** keep the `LICENSE` and `NOTICE` files with every copy and **give
  credit** to the original author.
- **Commercial or business use of any kind requires a separate written license.**
  Contact **mohammed.salem.sayed@gmail.com**.

This is a source-available license, not an OSI-approved open-source license.
Third-party dependencies named in the manifests keep their own licenses.
