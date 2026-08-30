# Milestone J notes — what is real, what remains

Status against [../MILESTONE_J_PLAN.md](../MILESTONE_J_PLAN.md). **333 tests green.**
All 14 days built. First §10.2 capability domain.

## Real after Milestone J

| Area | Module | Notes |
|---|---|---|
| Git adapter | `app/services/repo/git_adapter.py` | `GitAdapter(root, write_allowed=)`. Read: `status()`, `current_branch()`, `head_sha()`, `is_clean()`, `tracked_files()`, `log(path=, limit=)`, `blame(path, lines=)`, `show(sha)`, `diff(a, b, paths=)`, `changed_files(base_ref)`. Write (gated on `write_allowed()`): `create_branch(name)`, `commit(message, paths=)`. One `_run_git` — arg list only, 20 s timeout, rc capture, `GitError` on non-zero; a fixed bot identity via `-c user.*` so headless commits work without touching global config. **No network subcommand exists** (`fetch`/`pull`/`push`/`remote`/`clone` are not methods). |
| Symbol index | `app/services/repo/index.py` | `RepoIndex.build(root, files=)` → `FileFacts{path, module, lang, defs, imports, loc, approximate, error}` per source file. Python via `ast` (functions / classes / top-level assigns / `import` + `from … import`, relative imports resolved); other langs via a regex fallback flagged `approximate=True`. A syntactically broken Python file is skipped (flagged), the rest still index. `symbols()`, `file_for()`, `module_for_path()`, `is_internal()`. Bounded: `INDEX_MAX_FILES=2000`, 512 KiB/file. Derived — rebuilt per `HEAD` sha, never persisted (§11.3). |
| Module graph | `app/services/repo/graph.py` | `ModuleGraph.from_index(index)` — directed import edges between *internal* modules (longest-prefix resolution for `pkg.mod.name`). `dependencies(m, transitive=)`, `dependents(m, transitive=)` (BFS, cycle-safe), `reachable_dependents(changed)` = candidate blast radius, `fan_in(m)`. |
| Impact analysis | `app/services/repo/impact.py` | `analyze(index, graph, *, changed_paths, diff_text=, risk_globs=)` → `ImpactReport{changed_modules, dependent_modules (prod code only — tests reported separately), touched_symbols, dependent_symbols (approx, textual), tests_affected (test files importing the neighbourhood, fan-in-ranked, capped 50), risk_flags, approximate}`. Flags: `risk-path` (matches a `DEFAULT_RISK_GLOBS` entry), `public-api` (changed module fan-in ≥ 3), `wide-change` (> 3 dependent prod modules), `symbol-removed` / `signature-changed` (from the diff). Import reachability is a **superset heuristic**, not a proof — T0 stays authoritative. |
| Breadth classification | `app/services/repo/breadth.py` | `classify_breadth(interpreter_hint, impact)` → `BreadthAdvice{level: local|broad, why, escalate_review}`. `broad` when the hint says so, or `wide-change` / `risk-path` / `public-api`. Advisory only — never mutates `task_class` after PLANNING (§6). |
| Facade | `app/services/repo/facade.py` | `RepoIntelligence(root, write_allowed=, risk_globs=)` — lazily builds `GitAdapter` + `RepoIndex` + `ModuleGraph`, cached by `head_sha()` (rebuilt when HEAD moves). `context_block(objective)` → a `REPO CONTEXT` string (file/module counts, most-depended-on modules by fan-in, the import neighbourhood of files the objective names). `impact_for(changed_paths, diff_text)` → `ImpactReport`. `breadth(hint, impact)` → `BreadthAdvice`. |
| Capability tokens | `app/services/capability/registry.py` | `vcs.read` → `vcs.status` (git status/log/blame/diff). `vcs.write` → `vcs.read` + `vcs.branch` + `vcs.commit`. `vcs.branch` / `vcs.commit` are in `SIDE_EFFECTING_OPS`, so a tainted argument → DENY and they hit the risk-class approval gate. **No push token** — the adapter has no push path. |
| Orchestrator wiring | `orchestrator._repo_context` / `_repo_impact` | `self.repo` opt-in. At `INTERPRETING`/`PLANNING`: `context_block()` prepended to the listing the Interpreter + Planner see; a `REPO` event (file/module count + head). After the Builder diff, before VERIFYING: `impact_for(changed_paths, diff)` → an `IMPACT` event + a `repo`-sender `AgentMessage` carrying the breadth level and risk flags; a `broad` + `escalate_review` advice also logs a review-only `ROUTE` event. The impact's `tests_affected` (minus the contract's named target) are passed to `VerifierT0.verify(extra_targets=)`, which runs them alongside the named target — they widen the check, the named target still gates COMPLETED. Repo unset → behaviour identical to Milestone I. |
| Events | `REPO` (context built), `IMPACT` (the `ImpactReport`). |

## Not yet real / deferred

- **Import graph ≠ runtime graph** — conditional imports, plugin registries, entry-points,
  and dynamic dispatch are invisible. `tests_affected` is a superset heuristic for the common
  case; `dependent_symbols` / textual references over- and under-report. All approximate
  results carry `approximate=True`, and none of this gates COMPLETED — T0 does.
- **Python-first parsing** — non-Python files get the coarse regex fallback (`approximate`);
  breadth/impact quality drops for JS/TS/Go/Rust/etc. Tree-sitter / LSP is the deferred
  upgrade; the `FileFacts` shape is already language-neutral.
- **`vcs.write` is unused by the orchestrator** — the adapter supports a local branch + local
  commit on a `vcs.write`-granted step, but no milestone step currently requests it. Wiring
  a "work on a branch, commit the verified change" flow is a follow-up; **no push / PR path
  will ever be added** (non-goal).
- **Index is per-process** — rebuilt each task (cached within a run by `head_sha`). A
  persistent cross-process cache is deferred; §11.3 says indexes may be evicted freely.
- **No cross-repo / monorepo package graph** — single-repo only.
- **`code_edit_broad` orchestration** — the multi-file execution loop (Milestone D) plus this
  milestone's affected-test selection and breadth signal are the pieces; a dedicated
  broad-change flow (plan-level cloud review, staged application) is future work.

## Deferred past J (unchanged)

Research pipeline + evidence graph (§10.2, needs E — next domain); RAG / knowledge base
(needs the research pipeline); DOCX / PPTX authoring pipelines (§10.2, needs F); engine
adapters + expert modes (§10.2, needs this milestone); tree-sitter multi-language parsing.
