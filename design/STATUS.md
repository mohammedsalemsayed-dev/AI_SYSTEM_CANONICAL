# Status — what's actually built

Plain accounting of what works, what's a stub, and what's missing. The original
spec (`design/original-*.md/.docx`) describes a much larger target system; this
file is the honest boundary between that and the code in `nexus/`.

Shorthand used below: **built** = implemented and covered by tests; **slice /
foundation** = the interface and happy path exist but it hasn't been hardened or
stressed; **seam** = a named place where a real implementation still has to go.
None of the stub items were dropped — they're listed so they don't quietly vanish.

## How it was built

A close back-and-forth between me and Claude Code over roughly three days
(2026-08-28 to -30). I designed the architecture and wrote the per-stage plans in
`build-log/`; Claude drafted each stage; then we iterated — I reviewed every diff,
debugged what broke, and made the keep-or-cut calls, with the test suite as the
gate. So "built" here means *designed, wired, and test-passing* — written fast and
with AI in the loop — not *battle-tested in production*.

## What's real now

- durable event log and projections;
- local provider tier: `OllamaLLM` (interpret/plan) + `LocalBuilder` (agentic edit
  loop, `qwen3:8b`), benchmarked in `build-log/BUILDER_BENCH.md`, wired into a
  local-first -> cloud-escalation path;
- capability grants + a 7-rule policy engine; single-user approval protocol;
- Docker sandbox verification (tier-B); tier-C heavy-toolchain run is still a seam;
- checkpoints, crash recovery, reconciliation;
- multi-agent runtime (Critic, independent T2 verifier, Researcher);
- research/retrieval, repo intelligence + Git adapter, RAG/indexing;
- document/deck pipelines: Markdown/HTML (stdlib), DOCX/PPTX (python-docx /
  python-pptx), PDF (bundled dependency-free writer);
- SSE event streaming; the tool-adapter dispatch spine + a bounded tool-use loop
  for `ops` tasks;
- PostgreSQL event store (`PostgresEventLog`), verified against `postgres:17`;
- native desktop shell: `python desktop/build.py` produces the Windows NSIS + MSI
  installers, each bundling the Tauri shell + a frozen `nexus-server` sidecar.

## Still missing / not hardened

- Alembic migrations (schema is `CREATE TABLE IF NOT EXISTS`) + connection pooling;
  the other stores (`MemoryStore` / `ExperienceStore` / `RouteStatsStore`) are
  still SQLite-only;
- Redis/queue where justified;
- a real secrets vault;
- macOS / Linux desktop bundles;
- T2-verifier false-positive tuning now that it runs on cloud and can pause a task.

The per-stage sections below are the detailed record, kept in build order.

## Milestone B slice — `../nexus/` (Days 1–9 built; Day 10 pending)

A running vertical slice: `request -> TaskContract -> Plan -> edit (driven builder) ->
T0 verify -> result`, over an append-only SQLite event log with snapshot projections.
47 tests green (35 unit, 12 integration). Offline demo: `python -m app.cli.demo`.

Now real (slice scope only — see `../nexus/README.md` for the named seams that remain
stubbed):
- append-only event log + deterministic replay/projections;
- state machine **with transition-gate predicates** (design-notes §1);
- Interpreter (request -> contract) with the "no verifiable T0 -> WAITING_FOR_USER" rule;
- `task_class` taxonomy applied at interpretation;
- Planner (contract -> plan);
- Builder seam — `ScriptedBuilder` (tests) and `AgentSDKBuilder` (Choice-B executor);
- Verifier **T0 tier** — fresh checkout, apply diff, run the named pytest target;
- policy-decision + capability-grant **seam** (stub: allow + log);
- workspace-copy isolation (temp dir; not a hardened sandbox);
- `resume()` light recovery (interrupted task fails cleanly, workspace untouched).

Day 10 (premise test) — **done, premise holds**. Real loop = Agent SDK for
Interpreter/Planner/Builder on a Claude Pro subscription + VerifierT0 in the Docker Tier-A
sandbox. Two runs: 10 seeded single-function bugs (10/10 correct) and 5 real `more-itertools`
bug-fix commits (4/5 correct; the 1 miss was a behaviourally-right fix with the wrong exact
assert message, **caught by T0**, never marked COMPLETED). Combined **14/15 diffs correct,
zero false positives, 15/15 unaided T0 criterion**. Per MILESTONE_B_PLAN.md §7 the premise
holds. Surfaced weakness: the Builder doesn't reliably read the failing test before editing
(§14.1 prompt-tuning, not a blocker). See `../nexus/SLICE_FINDINGS.md`.

## Milestone C — security and authority (`../nexus/`, days 1–15; sandbox runtime pending)

132 tests green + 1 skipped. See `build-log/MILESTONE_C_NOTES.md`.

Now real (slice scope):
- capability registry + per-step scoped `CapabilityGrant` issuance (frozen from the Plan);
- deterministic Policy Engine (7 ordered rules) replacing the allow-all stub;
- structural taint (single tagging site + single side-effecting check);
- egress broker (per-task allowlist, default deny, tagged results);
- approval flow — `REQUIRE_APPROVAL` -> `WAITING_FOR_USER` -> `resume(approval=...)`;
- secret isolation — `SecretStore` + `scrub_env`, both sandbox backends scrub;
- audit event kinds + projection fields;
- Security gate — 26-case injection/abuse corpus + path-traversal battery + end-to-end
  objective-preservation.

Pending: the Tier-A sandbox is coded (`DockerSandbox`, arg-verified) but has not run a real
container — needs Docker Desktop installed, `slice-sandbox:pytest` built, and the
`--selftest` passing. Until then a dev-only non-isolating subprocess fallback is used and
refuses runs marked `allow_non_isolated=False`.

## Milestone D — recovery and progress (`../nexus/`, days 1–13)

180 tests green. See `build-log/MILESTONE_D_NOTES.md`.

Now real (slice scope):
- deterministic meaningful-progress scoring (six hard signals; novel-motion guard);
- structural loop detection (repeated action / error / diff-thrash; progress clears history);
- per-task_class patience;
- the escalation ladder (inspect / change_strategy / ask_user real; critic / research /
  stronger_model stubbed to E and G);
- multi-step `_execute` with per-step T0 measurement and ladder hand-off;
- task budget (`wall_clock_s` / `steps` / cost) with 80% soft event and 100% pause;
- checkpoints, idempotency-key tracking;
- restart reconciliation — `reconcile()` → RESUME / REPAIR / ESCALATE / NOOP, wired into
  `resume()` (replaces the old "interrupted → FAIL"); RESUME steers the state machine back to
  EXECUTING and re-runs, workspace untouched.

Stubbed: ladder rungs critic/research/stronger_model; coverage/lint/type-error signals
(defined, unpopulated); REPAIR escalates rather than auto-re-interpreting; cost dimension
unmetered on the subscription path.

## Milestone E — multi-agent coordination (`../nexus/`, days 1–14)

219 tests green. See `build-log/MILESTONE_E_NOTES.md`.

Now real (slice scope):
- **Critic** — one-shot pass, fresh context (contract + diff + target test, not the build
  narrative). T0 runs first; the Critic can never turn a T0-passing diff into a failure
  (a `reject` there is a logged `DISAGREEMENT`); a `reject` on a T0-fail drives one bounded
  retry with findings. Opt-in until the benchmark promotes it.
- **Structured `AgentMessage`** on every inter-role hand-off.
- **Independent T2 ensemble verifier** — model reconstructed-spec check from contract + diff
  alone, N contexts; advisory (T0 authoritative); escalates a T0-pass/T2-fail only when
  `risk_level ≥ medium` or a risky path.
- **Disagreement protocol** — name claims → discriminating test (T0) → synthesise → escalate
  if consequential.
- **Researcher** — query plan → egress-broker fetch (default deny) → claims + `EvidenceRecord`s
  at `retrieved_web` trust; wired to the D ladder `research` rung (fills that stub); the
  `critic` ladder rung is also real now.
- **Composition rule** + in-memory **RolePerformance** shadow tracking; `COMPOSITION` event.
- **Single-vs-multi benchmark** harness (`tests/benchmark/run_multiagent_bench.py`) — not yet
  run; needs the subscription; the Critic promote-to-default decision is gated on it.

Deferred: dedicated `research_web` orchestration (CD-research); real live egress fetch;
persistent RolePerformance (Milestone F); stronger-model ladder rung (Milestone G).

## Milestone F — memory and experience (`../nexus/`, days 1–14)

254 tests green. All 14 days built. See `build-log/MILESTONE_F_NOTES.md`.

Now real (slice scope):
- **Hierarchical memory** — `app/services/memory/store.py` SQLite `memory` table
  (`working` / `project` / `experience` / `system` tiers); append-mostly, supersession by
  id, no deletion. `retrieve()` is keyword + recency + tier + **trust-filtered**
  (`trust_min="workspace"` never returns `retrieved_web` / `doc_input`); never returns
  `QUARANTINED` experience, `STALE` only when flagged.
- **Context builder** — `memory/context.py` `build_context()` assembles the
  Interpreter/Planner working context (active decisions / constraints / open questions /
  artifact index / scoped retrieval hits), replacing the empty `ProjectMemory`. A
  superseded decision drops out of later context. `MEMORY` events on read and write.
- **Situation signature** — `experience/signature.py` `{task_class, sorted salient tags,
  tool set}`; retrieval matches on class + tag overlap (the §14.7 similarity idea without
  embeddings). Stable for the same contract.
- **Experience lifecycle** — `experience/lifecycle.py` `OBSERVED → CANDIDATE → VALIDATED →
  PROMOTED → MONITORED → STALE / QUARANTINED` as an `ALLOWED` map + one numeric §8 gate per
  transition. `experience/store.py` `ExperienceStore` (SQLite): `capture()` on a T0-pass
  completion → `OBSERVED`, auto-`CANDIDATE` if the `(signature, strategy)` pair is new;
  `try_validate()` (shadow-replay gate), `try_promote()` (stub offline eval + security
  human-approval branch, auto-`MONITORED`), `record_use()` / `sweep_stale()` /
  auto-quarantine.
- **Stub offline eval** — `experience/eval.py`: `GUARDRAIL_SET` fixture, deterministic
  `run_offline_eval`, `promote_decision` folding the §8 numeric gate with the
  security/policy/execution-scope human-approval branch. Real held-out harness is Milestone I.
- **Orchestrator wiring** — `_experience_advice()` retrieves matching `PROMOTED` / `MONITORED`
  experiences at PLANNING and emits an advisory `AgentMessage(sender="experience",
  intent="PROPOSAL")`; the Planner still writes a fresh plan. `_capture_experience()` on a
  T0-pass completion. `flag_catastrophic()` — automatic experience rollback (`any →
  QUARANTINED`, no debounce) on a narrow signal set; auto-fires when T2 contradicts a
  T0-passing result.
- **Persistent RolePerformance** — `RolePerformanceStore(memory=…)` persists per
  `(role, task_class)` to system memory (`MemoryStore.record_role_perf` /
  `latest_role_perf`); a fresh store over the same DB hydrates the accumulated numbers, so
  the composition rule reads performance across runs.
- **Event kinds** — `MEMORY`, `EXPERIENCE`, `EXPERIENCE_TRANSITION`.

Deferred: embedding / vector retrieval (CD-rag); the real held-out offline-eval harness
(Milestone I); benchmark rows in system memory (Milestone G); shadow-replay in practice may
never reach 5 matching tasks on a single-user machine — `CANDIDATE` is an acceptable
terminal state and experiences stay advisory regardless.

## Milestone G — routing and hardware (`../nexus/`, days 1–14)

271 tests green. All 14 days built. See `build-log/MILESTONE_G_NOTES.md`.

Now real (slice scope):
- **Provider registry** — `ProviderSpec` + `ProviderRegistry`; default seed has `agent_sdk`
  (subscription, cloud, the only `available` entry), `anthropic` (billed, opt-in), and three
  local tiers declared `available=False` (the local backend adapter is a named seam).
- **Static routing table (§7.1)** — one `RoutePolicy` per `task_class` + `escalation_reason()`
  predicates for the "escalate to cloud when …" column; `planning_arch` is always cloud.
- **Routing stats (§7.2)** — `RouteStatsStore` over the system memory tier; a run is scored
  only with a T1+ verification link; trailing 90 d / last 50; a model is eligible for a class
  at ≥ 20 scored runs.
- **Router** — static default → escalation / hardware-local override → data-driven score
  (`PROVISIONAL_WEIGHTS`, tagged; displaces the static pick only past a stability margin) →
  ε = 0.15 seeded exploration below eligibility.
- **Hardware modes** — `NORMAL…EMERGENCY` policy (`decide()`), a static-snapshot monitor seam;
  the router pauses on EMERGENCY and biases local on CONSERVATION+.
- **`stronger_model` ladder rung made real** — re-routes a stalled task to the best untried
  cloud provider and drives a re-plan; non-actionable on the default single-cloud registry.
- **Orchestrator wiring** — `router` / `route_stats` / `hardware` opt-in; `ROUTE` + `HARDWARE`
  events; `MODEL_RUN`s tagged and ingested on a verified completion; a fresh `Orchestrator`
  over the same system memory reuses the accumulated stats. Router unset → unchanged.
- **Offline eligibility seeder** — `tests/benchmark/seed_model.py` (not run; needs the
  subscription).
- **Event kinds** — `ROUTE`, `HARDWARE`.

Deferred: local model backend adapters (registry rows exist, unavailable); per-task role-LLM
swap from the chosen `ProviderSpec`; real hardware telemetry; logistic-regression weight fit
+ canary (Milestone I).

## Milestone I — optimization (`../nexus/`, days 1–14)

290 tests green. All 14 days built. See `build-log/MILESTONE_I_NOTES.md`.

Now real (slice scope):
- **Frozen guardrail suite** — `eval/guardrail.py` + a 12-task JSON fixture (each a
  self-contained module + T0 test with a known oracle); `GuardrailSuite.run(run_one)` with an
  injected runner, deterministic order, crash = fail. Target ~30.
- **Regression gate** — `eval/regression.py`: `check_regression()` passes iff aggregate drop
  ≤ 2 pp **and** no previously-passing guardrail task now fails. `RegressionBaseline` on the
  system memory tier; `certify()` fails closed with no baseline.
- **Offline eval** — `eval/offline_eval.py`: `OfflineEval.evaluate()` replays a held-out set
  with vs. without the change, then the guardrail gate; `decision="promote"` only at
  `heldout_n ≥ 10` + non-negative delta + guardrail held; security-scope subjects still need
  human approval. `ExperienceStore.try_promote(report=)` consumes a real `EvalReport`.
- **Canary** — `eval/canary.py` `CanaryController` (deterministic fractional cohort,
  HOLD/PROMOTE/ROLLBACK). Orchestrator (opt-in `canary_enabled`): a freshly-promoted
  experience's canary cohort underperforming → auto-`QUARANTINED` + `CANARY` event; a
  data-driven routing challenger underperforming → `route_freeze` in system memory + the
  router skips it.
- **Derived metrics** — `eval/metrics.py` `rebuild_metrics()` folds the event log into the
  §11.2 set (success by class, rework rate, verify-tier mix, escalation freq, budget-exhaust
  rate, quarantine count). Pure function, no store.
- **Standalone runner** — `tests/regression/run_guardrail.py` (real orchestrator; `--offline`
  scripted smoke path verified; real-model run not run here).
- **Event kinds** — `EVAL`, `CANARY`, `REGRESSION`.

Deferred: the real held-out numbers (need the subscription); guardrail suite growth to ~30;
wiring `OfflineEval` into an orchestrator-driven promotion job; logistic-regression weight
fit; scheduled/continuous guardrail runs (need Milestone H).

## Milestone H — desktop shell (`../nexus/`, days 1–14)

306 tests green. All 14 days built. See `build-log/MILESTONE_H_NOTES.md`.

Now real (slice scope):
- **Read models** — `app/ui/readmodels.py`: six pure folds of the event log — task list,
  per-task timeline (rows + state transitions + spend + verification), agents panel (latest
  `AgentMessage` per role), system-health strip (hardware mode / budget posture / canary
  count / quarantine count), metrics panel (wraps `rebuild_metrics`), routing tallies. No
  state; unmapped event kinds degrade to a generic row.
- **Event feed** — `app/ui/events.py` `EventFeed` tails the append-only `events` table by
  `seq`; `sse_frame()` formats Server-Sent-Events.
- **HTTP + SSE server** — `app/ui/server.py`: stdlib `http.server`, loopback-only, no runtime
  dependency. `GET /api/*` serve the read models as JSON; `GET /api/stream` tails the log as
  SSE; `GET /` + assets serve the frontend. `POST /api/tasks` returns 405 unless a `runner`
  is wired (`--allow-submit`), and a submitted task still passes every gate.
- **Frontend** — `app/ui/web/{index.html,app.js,style.css}`: one self-contained vanilla-JS
  page, no build step; subscribes to the stream and renders every panel; reconnects on drop.
  Replaces the prior static mock. Verified live against a seeded DB.
- **Entrypoint** — `app/ui/run_ui.py` (`--db`, `--port`, `--allow-submit`).

**Tauri packaging** (`../nexus/desktop/`, MILESTONE_H_TAURI_PLAN.md) — scaffolded:
`app/ui/paths.py` (frozen-aware `web_dir` / `default_db_path`), `app/ui/sidecar_main.py`
(PyInstaller entry, tested as a subprocess), and a complete Tauri v2 project — `Cargo.toml`,
`tauri.conf.json`, `capabilities/default.json` (shell-execute scoped to the sidecar only),
`src/main.rs` (spawn sidecar → TCP-poll → navigate → kill-on-exit), `build_sidecar.py`
(PyInstaller), `build.py` (one command, fails fast on a missing prerequisite), `gen_icons.py`
+ committed icons, `dist/splash.html`, `README.md`. The Rust side is written to the Tauri v2
API but **not `cargo build`-verified** here (no Rust toolchain); the Python half is tested.
`build.py` exits 2 with the missing prerequisites in this environment (asserted).

Deferred: producing the signed native binary (needs Rust + PyInstaller + platform build
tools + certs); a framework rewrite; SSE poll → push; async submit jobs; auto-update / tray /
single-instance; live-diff / evidence-graph / experience-browser panels (each = one fold +
one route).

## Milestone J — repo intelligence & Git adapter (`../nexus/`, days 1–14)

333 tests green. All 14 days built. First §10.2 capability domain. See
`build-log/MILESTONE_J_NOTES.md`.

Now real (slice scope):
- **Git adapter** — `app/services/repo/git_adapter.py` `GitAdapter`: deterministic wrapper
  over the `git` CLI. Read (status / branch / head / clean / tracked / log / blame / show /
  diff / changed-files) always available; `create_branch` / `commit` gated on a
  `write_allowed` predicate. One `_run_git` (arg-list, 20 s timeout, `GitError`).
  **No `fetch`/`pull`/`push`/`remote` method exists.**
- **Symbol index** — `app/services/repo/index.py` `RepoIndex`: per-file `FileFacts`
  (defs + imports) via Python `ast`, regex fallback for other languages (flagged
  `approximate`). Broken files skipped, not fatal. Bounded, derived, rebuilt per `HEAD`.
- **Module graph** — `app/services/repo/graph.py` `ModuleGraph`: internal import edges;
  `dependencies` / `dependents` (transitive, cycle-safe); `reachable_dependents` = blast
  radius; `fan_in`.
- **Impact analysis** — `app/services/repo/impact.py` `analyze()` → `ImpactReport`:
  changed → dependent modules (prod only), `tests_affected` (fan-in-ranked, capped),
  `risk_flags` (`risk-path` / `public-api` / `wide-change` / `symbol-removed` /
  `signature-changed`). Import reachability is a superset heuristic; T0 stays authoritative.
- **Breadth classification** — `app/services/repo/breadth.py` `classify_breadth()` →
  `BreadthAdvice{local|broad, …}`; advisory, never mutates `task_class`.
- **Facade + wiring** — `RepoIntelligence` (lazy, `head_sha`-cached); `orch.repo` opt-in:
  `REPO CONTEXT` block for the Interpreter + Planner (`REPO` event); post-build
  `ImpactReport` (`IMPACT` event + a `repo`-sender `AgentMessage`); the impact's affected
  tests are passed to `VerifierT0.verify(extra_targets=)` and run alongside the named target
  (widen the check; the named target still gates COMPLETED). Repo unset → unchanged.
- **Capability tokens** — `vcs.read`, `vcs.write` (`vcs.branch` / `vcs.commit` are
  side-effecting → taint + risk-class gated).
- **Event kinds** — `REPO`, `IMPACT`.

Deferred: tree-sitter multi-language parsing (Python-first now); a `vcs.write`-driven
work-on-a-branch flow (adapter ready, no step requests it; **no push/PR ever**);
persistent cross-process index; a dedicated `code_edit_broad` orchestration.

## Milestone K — research pipeline & evidence graph (`../nexus/`, days 1–14)

344 tests green. All 14 days built. Second §10.2 capability domain. See
`build-log/MILESTONE_K_NOTES.md`.

Now real (slice scope):
- **Evidence graph** — `app/services/research/evidence_graph.py`: sources + claims + edges
  (support / agrees / contradicts / answers); `contradictions()`, `is_primary()` (doc kind
  or official host outranks a generic page; a contradiction auto-resolves when one side has
  a primary source).
- **Injection scan** — `research/injection.py` `scan()`: pattern flags for override /
  role-injection / system-marker / tool-directive / exfiltration. A signal on the answer,
  not a content gate.
- **Decompose / cross-check / synthesis** — `research/{decompose,crosscheck,synthesize}.py`:
  question → 2–5 sub-questions; contradicting-claim detection + bounded (≤ 2) follow-up
  rounds + resolution; **claims-only** synthesis → `ResearchAnswer{sections+citation_ids,
  contested, citations, uncertainty}` at `retrieved_web` trust (the synthesis prompt carries
  no raw source text — unit-asserted).
- **Pipeline** — `research/pipeline.py` `ResearchPipeline.run()` ties it together over the
  Milestone E Researcher + egress broker.
- **Orchestrator** — `orch.research` opt-in; a `research_web` task runs the pipeline instead
  of plan→build→verify (`PLANNING`→`EXECUTING`→`OBSERVATION`→`VERIFYING`→`COMPLETED`), the
  `ResearchAnswer` as its artifact; `RESEARCH` + `SYNTHESIS` events.
- **Contract gate** — `validate_contract` is now task-class-aware: only the code-editing
  classes require a pytest T0 target.
- **§12** — source text never reaches a decision prompt; every research node is
  `retrieved_web` trust so it cannot originate a side effect; a planted "ignore previous
  instructions … exfiltrate" page is flagged and changes nothing (integration-asserted).
- **Event kinds** — `RESEARCH`, `SYNTHESIS`.

Deferred: real live egress fetch; HTML/PDF readability extraction; multi-hop provenance;
learned source reputation.

## Milestone L — RAG / knowledge base (`../nexus/`, days 1–14)

357 tests green. All 14 days built. Third §10.2 capability domain. See
`build-log/MILESTONE_L_NOTES.md`.

Now real (slice scope):
- **KnowledgeBase** — `app/services/kb/store.py`: SQLite documents + chunks; `ingest_text` /
  `ingest_file` / `ingest_dir` (text suffixes only, size + binary guards, sha-idempotent);
  every ingest runs the injection scan → `document.flags`. The retrieval index is derived
  (`rebuild_index()` from the chunk table, §11.3).
- **Chunking** — `kb/chunk.py`: heading-aware sliding window with overlap; deterministic.
- **Lexical retrieval** — `kb/lexical.py` `LexicalIndex` (Okapi BM25) as the stdlib fallback
  behind the `kb/retrieve.py` `Retriever` protocol — **a real embedding store / RAG framework
  slots in here** (§16: "do not build, integrate").
- **KB answer** — `kb/answer.py`: retrieve → per-chunk claim extraction (delimited
  `DOCUMENT CONTEXT`) → claims-only `research.synthesize` → `KBAnswer{sections+citations,
  uncertainty}` at `doc_input` trust; a no-match states the gap.
- **Research hook** — `ResearchPipeline(kb=)` adds `doc_input` KB sources per sub-question,
  so an answer blends library + web with per-source trust visible.
- **Orchestrator** — `orch.kb` opt-in; a `doc_analysis` task runs the KB answer path
  (`PLANNING`→`EXECUTING`→`KB`+`SYNTHESIS`→`OBSERVATION`→`VERIFYING`→`COMPLETED`); `KBAnswer`
  as artifact.
- **§12** — chunk text never reaches a decision prompt; every KB node is `doc_input` trust so
  it cannot originate a side effect; a planted-directive document is flagged and changes
  nothing.
- **Event kind** — `KB`.

Deferred: a real embedding / RAG framework behind `Retriever`; OCR + office-format parsing;
cross-encoder rerank; incremental re-index.

## Milestone M — authoring pipelines (`../nexus/`, days 1–14)

369 tests green. All 14 days built. Fourth §10.2 capability domain. See
`build-log/MILESTONE_M_NOTES.md`.

Now real (slice scope):
- **Document model** — `app/services/authoring/model.py`: `DocumentModel` / `Section` /
  `Block` (7 kinds) / `Citation`; `all_citations()` in first-reference order; `SlideDeck`
  (one slide per H2).
- **Renderers** — `authoring/render.py`: `Renderer` protocol; `MarkdownRenderer` +
  `HtmlRenderer` (stdlib). `DocxRenderer` / `PptxRenderer` render themed output via
  python-docx / python-pptx (`RendererUnavailable` if the package is missing);
  `PdfRenderer` uses a bundled dependency-free writer (`authoring/pdf_writer.py`,
  Helvetica, no install). `get_renderer(name, theme, images)` picks per-brief; the
  orchestrator writes every rendered format to disk when the run targets a real
  workspace.
- **outline → draft → review** — `authoring/{outline,draft,review}.py`: retrieval-grounded
  heading tree (KB-unsupported sections flagged); per-section claims-only body from KB claims
  + brief + memory context, `doc_input`-trust citations attached; a review pass (structural
  + LLM) → `Issue[]` (§7.1's review pass).
- **Pipeline** — `authoring/pipeline.py` `AuthoringPipeline.run()` → `AuthoringResult`; no
  filesystem write (the artifact is the rendered string).
- **Orchestrator** — `orch.authoring` opt-in; an `authoring` task runs the pipeline
  (`PLANNING`→`EXECUTING`→`AUTHORING`+`SYNTHESIS`→`OBSERVATION`→`VERIFYING`→`COMPLETED`);
  `deck` kind if the brief says "slide"/"deck"; a `blocking` review issue →
  `WAITING_FOR_USER`.
- **§12** — grounded claims keep their trust on each `Citation`; no write, no network; the
  rendered doc is a `workspace` artifact, not evidence.
- **Event kind** — `AUTHORING`.

Update (2026-08-30): DOCX/PPTX/PDF renderers are now real (python-docx / python-pptx /
bundled PDF writer), themed, and written to disk for real-workspace runs; deck auto-visuals
are opt-in (`NEXUS_DECK_IMAGES`). Still deferred: a revise loop; user-supplied templates.

## Milestone N — engine adapters & expert modes — **REMOVED (2026-08-30)**

Built during days 1–12, then **removed in full**. `app/services/engines/` (Godot /
Unreal / Android / Generic adapters + expert/domain profiles + `EngineRegistry`),
`EngineToolAdapter`, `orchestrator._engine_context`, the `ENGINE` event, and the
engine/expert-mode tests are all gone. Godot and Unreal were dropped first (commit
`73fabbb`); the remaining layer was dropped after.

**Why:** the layer only added planning-context guidance the local models mostly
ignored, needed per-engine toolchains it never shipped to be useful, and did not move
the app toward its actual goal ("one prompt / one doc → a working thing"). Not worth
the complexity.

**What stayed:** `AndroidVerifier` (`app/services/verify/verifier_t0`-tier,
`app/services/verify/verifier_android.py`) — a real T0 gate that runs `gradlew` JVM
unit tests for a Gradle project. It is verification, not an engine adapter, and it is
selected by a plain `settings.gradle[.kts]` check in `app/ui/runner.py`.

The fifth §10.2 capability domain ("Godot / Unreal / Android adapters + expert modes")
is therefore **not implemented**. See the root `README.md` scope section.

## Milestone O — automated model selection (`../nexus/`, days 1–10)

384 tests green. All 10 days built. Sixth and final §10.2 capability domain —
**all six are now FOUNDATION.** See `build-log/MILESTONE_O_NOTES.md`.

Now real (slice scope):
- **Feature vector** — `routing/features.py` `feature_row()`: the six §7.2 priors + bias,
  with measured aggregates replacing priors once a model is eligible.
- **Logistic weight fit** — `routing/weightfit.py`: stdlib batch gradient descent (sigmoid
  log-loss + L2), deterministic → `WeightSet{weights, n_train, val_accuracy, degenerate}`.
  Converges to ≥ 0.95 val-accuracy on separable data; degenerate/tiny input → a flagged
  `WeightSet`, not a crash.
- **Selection controller** — `routing/selection.py` `ModelSelectionController`: per
  `task_class`, flips `static` ↔ `data_driven`, persisted to system memory, gated by
  eligible-count + fit-quality + the Milestone I guardrail regression check. `demote()` is
  immediate; re-promotion needs a fresh `evaluate()`.
- **Router** — `Router(selection=)`: a data-driven class ranks candidates with the fitted
  `WeightSet`; otherwise `PROVISIONAL_WEIGHTS` (now the fallback, untouched).
- **Orchestrator** — `orch.selection` opt-in; consulted before routing (`SELECTION` event);
  a route-canary rollback (Milestone I) also `demote`s the class. Selection unset → routing
  unchanged.
- **Offline fitter** — `tests/benchmark/fit_weights.py` (reads a populated `RouteStatsStore`,
  writes per-class `WeightSet`s; **not run** — needs a scored-run corpus).
- **Scope** — changes which provider runs, never the policy/capability/taint path. Event
  kind `SELECTION`.

Deferred: a real weight fit (needs a scored-run corpus); non-linear models behind
`WeightSet`; per-role weight sets; automatic quarterly refit scheduling.

## Milestone P — artifact & version tracking (`../nexus/`, days 1–10)

396 tests green. All 10 days built. Removes "real artifact/version tracking" from the
"still requiring real implementation" list above. See `build-log/MILESTONE_P_NOTES.md`.

Now real (slice scope):
- **`ArtifactStore`** — `app/services/artifacts/store.py`: SQLite content-addressed blob
  store (sha-256, deduped) + a `version` chain per `logical_key`. `put()` (auto-parent-link,
  idempotent on `(logical_key, sha, task_id)`, truncation cap); `get` / `content` / `text` /
  `history` / `chain` (cycle-safe) / `latest_for` / `diff_versions` (unified diff for text
  kinds) / `archive_before` (**marks, never deletes** — §11.3).
- **Orchestrator** — `orch.artifacts` opt-in; the four deliverable paths store a versioned
  artifact (`diff` / `research_answer` / `kb_answer` / `document`) carrying the deliverable's
  own trust; the `ARTIFACT` event gains `store_id` / `sha` / `parent_id` / `logical_key`;
  `TaskResult.artifact_ref` is the store id when wired. Store unset → byte-identical to
  Milestone O.
- **Desktop shell** — `UIServer(artifacts=…)` + `GET /api/artifacts/{id}` → `{ref, text}`
  (read-only; `ref.trust` for badging).
- **§12** — `put()` requires an explicit trust; a research/KB artifact keeps
  `retrieved_web` / `doc_input`; no file write, no network call.

Deferred: filesystem materialisation (explicit `fs.write` step); binary artifact kinds (with
real Milestone M renderers); a UI artifact viewer; automatic archive-tier migration.

## Milestone Q — fault injection & recovery hardening (`../nexus/`, days 1–10)

423 tests green. All 10 days built. Removes "comprehensive test gates and fault injection"
from the "still requiring real implementation" list above. See
`build-log/MILESTONE_Q_NOTES.md`.

Now real (slice scope):
- **Fault toolkit** — `app/services/faults/`: `Fault`/`FaultPlan` (13 kinds, `on_call` /
  `sticky`); `FlakyLLM` / `FlakyRunner` / `FlakyBuilder` / `flaky_opener` raising the actual
  backend exception classes; `InterruptAfter` (a `BaseException`-based log hook that
  simulates a hard kill after a targeted event).
- **Fault suite** — `tests/fault/`: 20 tests (LLM refusal/timeout/garbage, every sandbox
  failure shape, non-applying / empty diff, builder exception, hard kill after
  PLAN/CHECKPOINT/ARTIFACT/VERIFICATION, egress flap) each asserting three invariants:
  safe terminal (a `COMPLETED` always has a passing T0), user workspace byte-identical, clean
  `reconcile()` + `resume()`. `run_fault_suite.py` → `FAULT_FINDINGS.md` (14/14 matrix PASS).
- **Hardening the suite forced** — `EgressBroker.fetch` now wraps the opener and raises a
  typed `EgressError` (allowed URL, transport failed) instead of letting a raw `URLError`
  crash `ResearchPipeline.run`; `Researcher` catches it and degrades to fewer sources +
  explicit uncertainty.

Deferred: real OS-level `SIGKILL` chaos (the hook stops at the log boundary); disk-full /
OOM triggers; model-output fuzzing beyond one shape; concurrency/race faults.

## Milestone R — telemetry & target-machine calibration (`../nexus/`, days 1–10)

435 tests green. All 10 days built. Removes "full telemetry and target-machine calibration"
from the "still requiring real implementation" list above. See
`build-log/MILESTONE_R_NOTES.md`.

Now real (slice scope):
- **Live telemetry** — `app/services/hardware/telemetry.py` `read_telemetry()`: real RAM %
  (Windows `ctypes GlobalMemoryStatusEx` / Linux `/proc/meminfo` / macOS `vm_stat`), CPU %
  (`getloadavg` / neutral), disk free %, and GPU temp/util/VRAM via a fixed-argv
  `nvidia-smi` probe (0.5 s timeout). Never raises — degrades to `source="live-degraded"`.
  Verified live on this host.
- **Calibration** — `hardware/calibration.py` `calibrate() -> HardwareProfile` (cpu count +
  50 ms micro-bench score, RAM/disk totals, 4 MiB disk-write bench, GPU block); `persist` /
  `load` to system memory; `is_stale` at 30 days. `python -m app.services.hardware.calibrate`.
- **`LiveHardwareMonitor`** — caches `read_telemetry()` for 2 s; drop-in for the static
  monitor (still the default).
- **Budget scaling** — `default_budget(task_class, profile=)` scales `wall_clock_s` by the
  calibrated cpu-bench score (0.5×–3× clamp) + a slow-disk bump; no profile → unchanged.
- **Orchestrator** — hardware sampling is now independent of routing: a `LiveHardwareMonitor`
  logs a real `HARDWARE` snapshot every task (health strip shows real numbers); an
  `EMERGENCY` pauses even with no Router.
- **Shell** — `system_health` / `GET /api/system` include a `hardware_live` block.
- **Schema / events** — `+ HardwareProfile`; `HardwareSnapshot` gains `cpu_percent` /
  `disk_free_percent`; `+ TELEMETRY` event.

Deferred: `psutil` / a cross-platform lib; non-NVIDIA GPU probes; the optional router
low-VRAM cloud bias (budget half landed, routing half is a follow-up); a background sampler;
power/battery reads; auto-recalibration scheduling.

## Milestone S — tool adapter framework (`../nexus/`, days 1–10)

445 tests green. All 10 days built. Removes **"tool adapter ecosystem"** from the "still
requiring real implementation" list above. Not a new §10.2 domain — the §5-C spine that
unifies the existing tool-adapter packages (git / research / KB / authoring / routing; the
`engine` adapter shipped here was removed 2026-08-30). See `build-log/MILESTONE_S_NOTES.md`.

Now real (slice scope):
- **Contract** — `app/services/tools/base.py`: `ToolOp` / `ToolManifest` / `ToolResult` /
  `DispatchContext` and a `runtime_checkable` `ToolAdapter` Protocol (`manifest()`,
  `invoke(op, args, ctx)`).
- **Registry** — `tools/registry.py` `ToolRegistry`: `register`/`get`/`all`/`find` +
  `manifest_block()` (one capability-tagged line per op, `MANIFEST_OP_CAP = 40`).
- **Dispatcher** — `tools/dispatch.py` `ToolDispatcher.run()`: builds an `ActionProposal`
  and calls the **existing** `PolicyEngine.decide` with the caller's `CapabilityGrant` — it
  adds no new gate. Unknown op / policy denial / adapter exception all become
  `ToolResult(ok=False)`, never a raise. On ALLOW the result's `trust` is stamped from the
  manifest `output_trust` — `retrieved_web` is never laundered to `workspace`.
- **Adapters** — `git` (read ops `vcs.read`; `git.branch`/`git.commit` gated, local only),
  `fs` (workspace-scoped by `relative_to` containment; `fs.write` gated), `net` (wraps the
  default-deny `EgressBroker`, `output_trust="retrieved_web"`), `shell` (`shell.exec` via the
  `SandboxRunner` seam), plus a generic MCP client for project `.mcp.json` servers. (The
  `engine` adapter shipped here was removed 2026-08-30.)
- **Orchestrator** — `self.tools` opt-in `ToolRegistry`; when set, `manifest_block()` is
  prepended to the planning context and `_tool(op, args, ctx)` dispatches + logs a `TOOL`
  event (and a `POLICY_DECISION` on denial). Unset → planning context + events byte-identical
  to Milestone R.
- **Events** — `+ TOOL`.

Deferred: routing the Builder / file edits through the dispatcher; a real tool ecosystem
(HTTP-API / shell / LSP / cloud-SDK adapters); LLM-driven op selection from the manifest;
per-op JSON-Schema arg validation; streaming / long-running tool ops.

## Milestone T — tool-use execution (`../nexus/`, days 1–10)

458 tests green. All 10 days built. Resolves Milestone S's deferred **"LLM-driven op
selection from the manifest"** and adds a **`shell` adapter**; `ops` becomes a first-class
deliverable flow. See `build-log/MILESTONE_T_NOTES.md`.

Now real (slice scope):
- **Shell adapter** — `tools/adapters/shell_tool.py` `ShellToolAdapter`: op `shell.exec` →
  capability `shell.run` (existing token, side-effecting, "sandboxed only"),
  `output_trust="tool_output"`. Delegates to the `SandboxRunner` seam; clamps timeout ≤ 120 s;
  bad args / refusal / non-zero exit / timeout → `ToolResult(ok=False)`, never a raise.
- **Tool-use loop** — `tools/loop.py` `ToolLoop.run(objective, ctx, manifest_block)`: the
  model is shown the manifest + transcript and emits ONE JSON object per turn —
  `{"op","args"}` (dispatched through the **Milestone S dispatcher** = the existing Policy
  Engine + grant) or `{"done","summary"}`. Bounded by `max_iters` (6) + a `parse_budget` (2);
  a policy-denied op is a transcript turn (`denials`++), not a stop. Deterministic — no
  wall-clock / random input.
- **`ops` flow** — `orchestrator._run_tool_task`: `self.tool_loop` opt-in; PLANNING →
  EXECUTING (runs the loop **on a workspace copy**) → VERIFYING → COMPLETED with a `T0` pass
  `VerificationRecord`; a loop `ok=False` → FAILED cleanly. Per-op `TOOL` + per-denial
  `POLICY_DECISION` + one `TOOL_LOOP` summary; the transcript is a `tool_output`-trust
  artifact. `_tool_task_grant` grants only the union of non-side-effecting registered ops
  (plus an explicit `self.tool_task_capabilities` opt-in) — `shell.run` is never auto-granted.
- **Events** — `+ TOOL_LOOP`.

Deferred: routing the Builder (`code_edit_*`) through the loop; parallel / batched tool
turns; native tool-use blocks in place of JSON turns; per-op retry / self-repair;
adapters beyond `shell`; streaming a long `shell.exec`.

## Milestone U — loop detection for the tool-use loop (`../nexus/`, days 1–8)

463 tests green. All 8 days built. The Milestone T tool-use loop now carries the §14.4
structural progress guard that `_execute` has had since Milestone D. See
`build-log/MILESTONE_U_NOTES.md`.

Now real (slice scope):
- **Detector wiring** — `ToolLoop(detect_loops=True, loop_detector=None)`: a fresh
  `LoopDetector` per `run()` + an `_ok_hashes` set. `action_hash` / `normalize_error` /
  `LoopDetector` imported unchanged from `app.services.progress.loop`.
- **Per-turn record** — `made_progress = result.ok and action_hash(op,"",args) not in ok_hashes`;
  `detector.record(...)` each dispatched turn. A new op that succeeds clears the history
  (D's false-positive guard); a repeated failing op accumulates `repeated_action` +
  `repeated_error`. `report.flags` attach to the `result` transcript turn.
- **Early stop** — `report.loop_risk` → a `{"kind":"loop_risk"}` turn and
  `ToolLoopResult(loop_risk=True, loop_flags=[...])` **before** `max_iters`.
- **Escalation** — `orchestrator._run_tool_task`: `loop_risk` → a `CLARIFICATION` +
  `WAITING_FOR_USER` (mirrors the `_execute` `StalledEscalation` path) — asks the user, never
  silently retries. Iteration-cap / parse-budget still → `FAILED`.
- **Observability** — one `PROGRESS` summary event per task
  (`classification: LOOP_RISK | done | incomplete`); `TOOL_LOOP` gains `loop_risk` +
  `loop_flags`.
- **Opt-out** — `detect_loops=False` restores the exact Milestone T iteration-cap behaviour;
  `max_iters` still bounds the loop regardless.

Deferred: an escalation *ladder* for the tool loop (stronger model / critic before the user);
`ProgressService` patience / `STALLED` classification for tool turns; threshold tuning from
real transcripts.

## Milestone V — per-changed-file policy checks (`../nexus/`, days 1–7)

471 tests green. All 7 days built. Closes a real §14.1 gap — the risk-class human-approval
gate (`*auth*`, `*/migrations/*`, `*secret*`, `*/payments/*`, `*.pem`, …) now applies to the
**files a build changes**, not just the workspace root the step proposal carried. See
`build-log/MILESTONE_V_NOTES.md`.

The gap: `_run_step` proposes once per step with `arguments={"path": ws}` — the workspace
root — so `rule_risk_class_needs_approval` never matched a real file, and a `code_edit_local`
task rewriting `app/auth/login.py` or a DB migration was applied with no `APPROVAL_DECISION`.

Now real (slice scope):
- **`Orchestrator.per_file_policy: bool = False`** opt-in. Off → `_run_step` byte-identical
  to Milestone U (a migration edit still sails through — the gap V closes).
- **`_per_file_policy(...)`** — after the builder runs and **before** the step's artifact is
  recorded, one `file.write` `ActionProposal` per **relative** path in `out.changed_paths`,
  each through the **existing** `PolicyEngine.decide` + the step's `CapabilityGrant`. `ALLOW`
  → a logged `POLICY_DECISION` (`scope="per-file"`, `path`); `REQUIRE_APPROVAL` → `ApprovalPause`
  keyed to the **step proposal's** `action_id` (so approve/resume clears it); `DENY` (out of
  scope / tainted / operation-not-granted) → `BuildError`.
- No new rule, no new gate, no new event kind. Approval stays step-scoped. Deterministic; the
  flag is config (no persistent state; `reconcile()` unaffected).

Deferred: routing each write through `FsToolAdapter`/`ToolDispatcher` as it happens (needs
the Builder to *declare* writes); per-file approval granularity; content inspection (secret
scanning) as a verifier tier; flipping `per_file_policy` on by default.
