# Milestone J — Repo Intelligence & Git Adapter Plan

> **Cross-reference**
> - Role: Build plan for the first §10.2 capability domain — a deterministic Git adapter and a repo model (symbol index + module dependency graph + blast-radius analysis) behind the §5-C tool boundary.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §6 (`code_edit_broad` in the task taxonomy), §7.1 (route escalation "plan touches > N modules or security-relevant paths"), §10.2 (capability domain: *Repo intelligence + Git adapter → `code_edit_broad`, "what could this change break"*), §11.3 (indexes are derived and rebuildable), §12 (tool outputs are `tool_output` trust — facts, not directives), §14.3 (tainted argument on a side-effecting op → DENY).
> - Downstream (depended on by): the Research pipeline (§10.2), engine adapters + expert modes (§10.2 — "prereq: repo intelligence"), a future repo-aware `code_edit_broad` orchestration.
> - Predecessors: C (capability registry + policy engine + sandbox — the boundary this domain sits behind), B (the edit→verify loop it augments). Continues the `milestone_b/` tree.

---

## 1. Purpose

The Builder edits temp-dir copies with no model of the repository. `list_workspace()` is a
flat file list; there is no symbol index, no import graph, no notion of what a change could
break, and no first-class Git surface beyond the diff plumbing in `workspace_copy.py`. That
caps the system at `code_edit_local` — one file, one test.

Milestone J adds the first §10.2 capability domain:

- a **Git adapter** — a deterministic, capability-gated wrapper over the `git` CLI (status,
  branch, log, blame, show, diff, changed-files; branch/commit behind `vcs.write`, never
  push);
- a **repo model** — a per-workspace symbol index (Python `ast` + a generic fallback) and a
  module **dependency graph** from the import edges;
- **blast-radius analysis** — given a diff, compute the dependent modules, the tests that
  cover them, and a set of **risk flags** ("what could this change break");
- **breadth classification** — reconcile the Interpreter's `code_edit_local` /
  `code_edit_broad` guess with the *measured* dependent-module count and risk flags;
- **orchestrator wiring** — a repo-context block for the Planner, an `ImpactReport` after the
  Builder's diff that drives *which* tests T0 runs and feeds the §7.1 route escalation and the
  policy risk-class check.

Guiding rules:
- **§5-C boundary** — every filesystem / `git` call is an operation the Policy Engine sees.
  New capability tokens `vcs.read` (default in a plan step's grant) and `vcs.write` (explicit,
  approval-gated).
- **§11.3** — the index and the graph are derived, held per task, rebuildable from the tree;
  optionally cached by `HEAD` sha. Never a source of truth.
- **§12 / §14.3** — `git`/index output is `tool_output` trust: facts (paths, shas, edges)
  inform routing and verification; free text never authorises an action. `vcs.write` with a
  tainted argument is denied like any side-effecting op.
- **Non-goal (unchanged)** — no autonomous publish: `vcs.write` covers a local branch + a
  local commit only, on an explicit step; **no push, no PR, no remote**.
- **§6 immutability** — J does not mutate `task_class` after `PLANNING`; measured breadth is
  an *advisory* the Planner and router read.

## 2. In scope

| Concern | Milestone J implementation |
|---|---|
| Git adapter | `repo/git_adapter.py`: `GitAdapter(root)`. Read: `status()`, `current_branch()`, `head_sha()`, `is_clean()`, `tracked_files()`, `log(path=, limit=)`, `blame(path, lines=)`, `show(sha)`, `diff(a, b, paths=)`, `changed_files(base_ref)`. Write (token `vcs.write`): `create_branch(name)`, `commit(message, paths)`. All via one `_run_git(args, timeout)` — arg list only, never a shell string; captures rc/stdout/stderr; `GitError` on non-zero. No network subcommands are exposed. |
| Symbol index | `repo/index.py`: `RepoIndex.build(root, files=None)`. Per tracked source file → `FileFacts{module, path, lang, defs[], imports[], loc}`. Python via `ast` (functions, classes, top-level assignments, `import` / `from … import`); other languages via a generic regex fallback (def/func/class + import-like lines), flagged `approximate=True`. `symbols()` (name → sites), `file_for(module)`, `defs_in(path)`. |
| Module graph | `repo/graph.py`: `ModuleGraph.from_index(index)`. Directed import edges module→module. `dependencies(m)`, `dependents(m)` (both with a `transitive=` flag, cycle-safe), `reachable_dependents(changed: set)` = the candidate blast radius. |
| Impact analysis | `repo/impact.py`: `analyze(index, graph, *, changed_paths, changed_symbols=None, risk_globs=…) -> ImpactReport`. Fields: `changed_modules`, `dependent_modules` (transitive), `touched_symbols`, `dependent_symbols` (approx, textual), `tests_affected` (test files that import a changed/dependent module), `risk_flags` (`public-api` = a changed symbol imported by ≥ `PUBLIC_FANIN` modules; `risk-path` = a changed path matches a policy risk-glob; `symbol-removed` / `signature-changed` from the diff; `wide-change` = `len(dependent_modules) > BROAD_MODULES`). |
| Breadth classification | `repo/breadth.py`: `classify_breadth(interpreter_hint, impact) -> BreadthAdvice{level: "local"|"broad", why, escalate_review: bool}`. `broad` when the hint says so, or `wide-change`, or a `risk-path` flag. Advisory only. |
| Facade | `repo/facade.py`: `RepoIntelligence(root)` — builds `GitAdapter` + `RepoIndex` + `ModuleGraph` (lazily, cached by `head_sha()`); `context_block(objective)` → a `REPO CONTEXT` string (tracked-file count, top modules by fan-in, the import neighbourhood of files the objective names); `impact_for(changed_paths, diff_text)` → `ImpactReport`. |
| Capability tokens | `capability/registry.py` + `vcs.read` (→ `vcs.status`, `vcs.log`, `vcs.diff`) and `vcs.write` (→ `vcs.branch`, `vcs.commit`; **side-effecting**, so tainted-arg → DENY and risk-class → approval). |
| Orchestrator wiring | `self.repo = None` opt-in. At `PLANNING`: build `RepoIntelligence`, prepend `context_block()` to the Planner listing, log a `REPO` event. After the Builder diff, before verify: `impact_for(...)` → log an `IMPACT` event; union `tests_affected` into the T0 target set (run the affected tests, not only the named one); pass `risk_flags` to the route-escalation inputs (`modules_touched`, `risk_level`) and surface them to the Critic. Repo unset → unchanged. |
| Events | `REPO` (context built: file count, module count, head sha), `IMPACT` (the `ImpactReport`). |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Tree-sitter / LSP multi-language parsing | later — Python `ast` + a regex fallback is the slice; the `FileFacts` shape is language-neutral |
| Semantic call graph / dynamic-dispatch resolution | later — the slice is import-edge + textual-reference approximation, flagged as such |
| Cross-repo / monorepo package graphs | never in the single-repo slice |
| `git` rebase / merge / conflict resolution | not needed for edit→verify; a separate domain if ever |
| Auto-commit / auto-PR / push | **non-goal** — `vcs.write` is local branch + local commit on an explicit step only |
| Blame-based ownership / reviewer routing | later (needs the research/notify domains) |
| Persisted index across processes | §11.3 — derived and rebuildable; an in-process cache keyed by `head_sha` is enough |

## 4. Component layout

```
app/services/repo/
  git_adapter.py   GitAdapter over the git CLI (read + gated write); GitError
  index.py         RepoIndex — FileFacts (defs + imports) per file; ast + regex fallback
  graph.py         ModuleGraph — import edges; dependencies/dependents/reachable
  impact.py        analyze(...) -> ImpactReport (blast radius, tests_affected, risk_flags)
  breadth.py       classify_breadth(hint, impact) -> BreadthAdvice
  facade.py        RepoIntelligence — bundles the above; context_block / impact_for
app/schemas/contracts.py   + FileFacts, ImpactReport, BreadthAdvice, GitStatus
app/events/log.py          + REPO, IMPACT
app/services/capability/registry.py  + vcs.read / vcs.write (+ ops)
app/orchestration/orchestrator.py    opt-in self.repo; PLANNING context; post-build impact;
                                     affected-test selection; risk flags -> routing + policy
tests/
  unit/         test_git_adapter, test_repo_index, test_module_graph, test_impact, test_breadth
  integration/  test_repo_context_at_planning, test_impact_selects_affected_tests,
                test_broad_change_flagged
```

## 5. Work breakdown (~14 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `repo/git_adapter.py` — read ops + `GitError` + `_run_git` (arg-list, timeout, rc capture); `create_branch` / `commit` behind a passed-in "write allowed" check. Unit tests over a temp repo fixture (history, a branch, a dirty file). |
| 3–4 | `repo/index.py` — `RepoIndex.build`; Python `ast` extraction of defs + imports; generic regex fallback with `approximate=True`; `symbols()` / `file_for()`. Unit tests over a fixture package. |
| 5–6 | `repo/graph.py` — `ModuleGraph.from_index`; `dependencies` / `dependents` (direct + transitive, cycle-safe); `reachable_dependents`. Unit tests incl. an import cycle. |
| 7–8 | `repo/impact.py` — `analyze()` → `ImpactReport`; changed→dependent modules; `tests_affected` (test files importing the neighbourhood); `risk_flags` (reusing `DEFAULT_RISK_GLOBS`, `PUBLIC_FANIN`, diff-derived `symbol-removed` / `signature-changed`). Unit tests: a leaf change, a widely-imported change, a risk-path change. |
| 9 | `repo/breadth.py` — `classify_breadth` advisory; unit tests for each `broad` trigger. |
| 10–11 | `repo/facade.py` — `RepoIntelligence` (lazy, `head_sha`-cached) + `context_block()` + `impact_for()`. `capability/registry.py` — `vcs.read` / `vcs.write` tokens + ops; `vcs.write` in `SIDE_EFFECTING_OPS`. Unit tests: context block shape; `vcs.write` op is side-effecting. |
| 12 | Orchestrator wiring — `self.repo` opt-in; `REPO` event + Planner context at `PLANNING`; post-build `impact_for` → `IMPACT` event → affected-test union into the `VerifierT0` target; `risk_flags` → `modules_touched` / `risk_level` for the route escalation and the policy risk-class. |
| 13 | Integration — repo context reaches the Planner listing; a change to a module imported by 3 others runs those modules' tests at T0; a change spanning > `BROAD_MODULES` or a risk path logs a `broad` `BreadthAdvice` and (with the router wired) escalates to cloud review. |
| 14 | Regression; `milestone_b/MILESTONE_J_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — `GitAdapter` reports branch / head / clean-state / tracked files / a file's log
  correctly on a fixture repo, and raises `GitError` (not a crash) on a bad ref;
  `RepoIndex.build` finds every top-level def and import in a Python fixture and falls back
  (flagged `approximate`) for a non-Python file; `ModuleGraph.dependents` is correct
  transitively and terminates on a cycle; `analyze()` returns the right `dependent_modules`
  and `tests_affected` for a leaf vs a widely-imported change and sets `risk-path` for a
  change under a risk-glob; `classify_breadth` returns `broad` for each trigger and `local`
  otherwise.
- **Integration** — with `orch.repo` wired, a task's Planner listing contains a `REPO
  CONTEXT` block and a `REPO` event is logged; after the Builder edits a module that 3 test
  files transitively import, T0 runs all of them (an `IMPACT` event lists them in
  `tests_affected`); a change flagged `wide-change` or `risk-path` produces a `broad`
  `BreadthAdvice`. Repo unset → behaviour identical to Milestone I.
- **Failure** — a malformed repo (no `.git`, or an unreadable file) degrades to the flat
  listing + an empty `ImpactReport`, never a 500; an index build over a syntactically broken
  Python file skips that file (flagged) and indexes the rest.
- **Security** — a `vcs.write` (`vcs.branch` / `vcs.commit`) operation is in
  `SIDE_EFFECTING_OPS`, so a tainted argument is DENIED and it hits the risk-class approval
  gate; the adapter exposes **no** network subcommand (`fetch` / `pull` / `push` / `remote`);
  `git`/index text is consumed as `tool_output` facts only.
- **Recovery** — `reconcile()` + `resume()` work with the repo facade attached; the index is
  rebuilt on resume (it is derived), the event log is untouched.
- **Benchmark** — n/a (no model calls added; the index and graph are deterministic).

## 7. Tunable starting values

- `BROAD_MODULES` = **3** — > 3 transitive dependent modules ⇒ `wide-change` (matches the
  §7.1 `code_edit_broad` "> N modules" trigger; reuse `table.BROAD_MODULE_THRESHOLD`).
- `PUBLIC_FANIN` = **3** — a changed symbol imported by ≥ 3 modules ⇒ `public-api` flag.
- `INDEX_MAX_FILES` = **2000**, `INDEX_MAX_BYTES_PER_FILE` = **512 KiB** — skip larger.
- `GIT_TIMEOUT_S` = **20**.
- `tests_affected` cap = **50** files (largest fan-in first).

## 8. Risks

- **Textual reference approximation** — without a real call graph, `dependent_symbols` /
  `references()` over-report (a name collision) and under-report (dynamic access). Mitigate:
  they are advisory (they widen the *test* set and inform the Planner, they do not gate
  COMPLETED — T0 still does), and every approximate result is flagged.
- **Import graph ≠ runtime graph** — conditional imports, plugin registries, and
  entry-points are invisible. `tests_affected` is therefore a *superset heuristic* for the
  common case, not a proof; T0 remains authoritative.
- **Index cost on a large repo** — bounded by `INDEX_MAX_FILES` / per-file byte cap and built
  once per `head_sha`; still O(files) per task. A persistent cache is deferred (§11.3 says
  it may be evicted freely anyway).
- **`vcs.write` scope creep** — the temptation is auto-commit. Held: `vcs.write` is a local
  branch + local commit on an explicit step, no remote subcommand exists in the adapter, and
  it is side-effecting so it inherits the taint + approval gates.
- **Non-Python repos** — the regex fallback is coarse; breadth/impact quality drops. That is
  acceptable for the slice and flagged; tree-sitter is the deferred upgrade.

## 9. Deliverables

- `app/services/repo/` — `git_adapter.py`, `index.py`, `graph.py`, `impact.py`,
  `breadth.py`, `facade.py`.
- `vcs.read` / `vcs.write` capability tokens; `REPO` / `IMPACT` event kinds.
- Orchestrator: opt-in `RepoIntelligence`; Planner repo-context at `PLANNING`; post-build
  `ImpactReport` driving affected-test selection + the route escalation + the policy
  risk-class.
- Test suite: the current 314 green, plus unit (git adapter / index / graph / impact /
  breadth) and integration (repo context at planning / affected-test selection / broad-change
  flag).
- `milestone_b/MILESTONE_J_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: "Repo intelligence + Git adapter" (§10.2 domain
  1) moves to FOUNDATION; `code_edit_broad` gains a measured breadth signal.
