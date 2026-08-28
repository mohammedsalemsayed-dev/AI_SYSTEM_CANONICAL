# Milestone N — Engine Adapters & Expert Modes Plan

> **Cross-reference**
> - Role: Build plan for the fifth §10.2 capability domain — per-engine project adapters (Godot / Unreal / Android + a generic fallback) and expert prompt profiles that make the Interpreter / Planner / Builder engine-aware.
> - Authority: Implementation plan; subordinate to the Complete Claude-Code Spec and [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md).
> - Upstream (consumes): [DESIGN_TIGHTENING.md](DESIGN_TIGHTENING.md) §10.2 (capability domain 5: *Godot / Unreal / Android adapters + expert modes → engine-aware coding, expert prompt profiles*, "prereq: repo intelligence"), §5-C tier C (heavy engine builds — snapshotted build sandbox), §14.6 (sandbox tiers).
> - Downstream: none — engine adapters are a leaf capability that enriches `code_edit_*` in an engine project.
> - Predecessors: J (repo intelligence — the project model these adapters extend), C (sandbox tiers). Continues the `milestone_b/` tree.

---

## 1. Purpose

Repo intelligence (Milestone J) models any repo as modules + an import graph. It does not
know that a `project.godot` means "scenes are `.tscn`, scripts are `.gd` attached to nodes,
prefer signals over polling", or that an `*.uproject` means "gameplay classes derive from
`AActor`, build with UnrealBuildTool". A Builder editing an engine project without that
context writes plausible-but-wrong code.

Milestone N adds:

- **engine adapters** — `detect(root)` + a structured `EngineInfo` (engine, version hint,
  source dirs, asset dirs, build command, test command, file conventions) for **Godot**,
  **Unreal**, **Android/Gradle**, and a **generic** fallback (pyproject / package.json /
  go.mod / Cargo.toml);
- **expert profiles** — a prompt fragment per engine (and a few domain profiles) that the
  Interpreter / Planner / Builder load when the engine is detected or the user asks;
- **orchestrator wiring** — detect at `INTERPRETING`, prepend the expert profile to the
  planning context, log an `ENGINE` event carrying the engine's own build/test command as a
  `verify_hint` (engine-native verification — running the engine binary — is a documented
  sandbox-tier-C seam, not built here).

Guiding rules:
- **Advisory, additive** — an adapter changes the *context* the models get and records the
  engine's verify command; it does not change the state machine, the policy path, or T0. An
  engine project with a pytest T0 still verifies through T0.
- **Detection is read-only** — adapters read workspace files (`workspace` trust); no writes,
  no engine binary invocation.
- **§5-C tier C** — a real `godot --headless` / UnrealBuildTool / `gradle test` run needs the
  engine toolchain and a heavier sandbox; N ships the *command* and the seam, the run is
  deferred.
- **Fallback always resolves** — `GenericAdapter` matches any repo, so `detect()` never
  returns nothing.

## 2. In scope

| Concern | Milestone N implementation |
|---|---|
| Adapter contract | `engines/base.py`: `EngineAdapter` protocol — `name`, `detect(root) -> float` (0..1 confidence), `info(root) -> EngineInfo`, `expert_profile() -> ExpertProfile`. `EngineInfo{engine, version_hint, source_globs[], asset_globs[], build_cmd, test_cmd, conventions{}, entrypoints[]}`. `ExpertProfile{name, prompt, do[], dont[]}`. |
| Godot | `engines/godot.py`: detect `project.godot` (+ `*.tscn` / `*.gd` presence raises confidence); `version_hint` from the `config_version` / `[application] config/features`; source `*.gd` / `*.cs`, assets `*.tscn` / `*.tres` / `*.png`; `build_cmd = "godot --headless --export-release"`, `test_cmd = "godot --headless --run-tests"` (GUT/GdUnit hint); conventions: snake_case files, one script per node, signals over `_process` polling. |
| Unreal | `engines/unreal.py`: detect `*.uproject`; modules from `Source/*/*.Build.cs`; `version_hint` from the `.uproject` `EngineAssociation`; source `Source/**/*.cpp|*.h`, content `Content/**`; `build_cmd` = the platform UBT invocation, `test_cmd` = `UnrealEditor-Cmd ... -ExecCmds="Automation RunTests ..."`; conventions: `A`/`U`/`F`/`E` prefixes, `UPROPERTY`/`UFUNCTION` macros, gameplay in modules not the editor target. |
| Android | `engines/android.py`: detect `settings.gradle[.kts]` + an `AndroidManifest.xml` (or `com.android.application` in a `build.gradle`); modules from `settings.gradle` `include(...)`; `version_hint` from `compileSdk` / AGP version; `build_cmd = "./gradlew assembleDebug"`, `test_cmd = "./gradlew testDebugUnitTest connectedCheck"`; conventions: package-by-feature, `ViewModel` not logic in `Activity`, resources in `res/`. |
| Generic | `engines/generic.py`: always `detect -> 0.05`; `info` picks the ecosystem from `pyproject.toml` / `package.json` / `go.mod` / `Cargo.toml` / `pom.xml` and fills `build_cmd` / `test_cmd` accordingly (`pytest -q`, `npm test`, `go test ./...`, `cargo test`, `mvn test`); a neutral profile. |
| Registry | `engines/registry.py`: `EngineRegistry(adapters=)` — `detect(root) -> (adapter, EngineInfo)` = the highest-confidence adapter (ties → most specific, generic last); `for_name(name)`. |
| Expert profiles | `engines/profiles.py`: the per-engine `ExpertProfile`s + a few domain profiles (`systems`, `data-pipeline`, `web-frontend`, `security-review`) selectable by name via `contract.constraints` (e.g. `"expert: security-review"`). `render(profile) -> str` — a compact `EXPERT MODE` block (`do` / `dont` bullets). |
| Schemas | `+ EngineInfo`, `+ ExpertProfile` (pydantic) in `contracts.py`. |
| Orchestrator wiring | `self.engines = None` opt-in (an `EngineRegistry`). At `INTERPRETING`: `detect(workspace_path)`; if confidence ≥ `ENGINE_MIN_CONF` **or** a `"expert: <name>"` constraint is present, prepend `EXPERT MODE` + a short `ENGINE` context (engine, conventions, verify command) to the listing the Interpreter + Planner see; log an `ENGINE` event `{engine, confidence, build_cmd, test_cmd, profile}`. The `test_cmd` is surfaced to the Planner as the engine-native check to run; T0 (if the contract names one) still gates. Engines unset → unchanged. |
| Events | `ENGINE` (engine, confidence, build/test cmd, profile name). |

## 3. Out of scope (deferred)

| Deferred | Filled in |
|---|---|
| Running the engine toolchain (`godot`, UBT, `gradle`) | §5-C tier C — a snapshotted heavy-build sandbox; N ships the command + the seam |
| Engine-native test verification as a T-ladder tier | later — needs the toolchain; the `test_cmd` is advisory now |
| Scene / blueprint / layout parsing | later — adapters read text project files, not binary `.uasset` / `.tscn` internals beyond globs |
| Asset pipeline (import, cook, bake) | never in the slice |
| More engines (Unity, Bevy, iOS/Xcode, Flutter) | additive — a new `EngineAdapter` + profile |
| Per-engine repo-intelligence parsers (GDScript / C++ AST) | later — J's Python `ast` + regex fallback still applies; a GDScript parser is a J follow-up |

## 4. Component layout

```
app/services/engines/
  base.py       EngineAdapter protocol; EngineInfo; ExpertProfile
  registry.py   EngineRegistry.detect(root) -> (adapter, info)
  godot.py  unreal.py  android.py  generic.py
  profiles.py   ExpertProfile catalog + render()
app/schemas/contracts.py   + EngineInfo, ExpertProfile
app/events/log.py          + ENGINE
app/orchestration/orchestrator.py   opt-in self.engines; detect + expert-mode context at INTERPRETING
tests/
  unit/         test_engine_detect, test_engine_info, test_expert_profiles, test_engine_registry
  integration/  test_engine_context_at_planning
```

## 5. Work breakdown (~12 working days)

| Day | Deliverable |
|---|---|
| 1–2 | `engines/base.py` (protocol + `EngineInfo` + `ExpertProfile`) + `engines/generic.py` (ecosystem sniff → build/test cmd). Unit tests over fixture repos (pyproject / package.json / go.mod). |
| 3–4 | `engines/godot.py` — detection + `EngineInfo` from `project.godot`. Unit tests: a Godot fixture detects with high confidence and the right globs / commands; a non-Godot repo → 0. |
| 5–6 | `engines/unreal.py` — `*.uproject` + `Source/*/*.Build.cs`. Unit tests. |
| 7–8 | `engines/android.py` — `settings.gradle` + manifest. Unit tests. |
| 9 | `engines/registry.py` — highest-confidence resolution, generic last. Unit tests: a repo that looks like both Gradle and generic picks Android; an empty repo picks generic. |
| 10 | `engines/profiles.py` — the profile catalog + `render()`; `"expert: <name>"` constraint selection. Unit tests: each engine profile renders a bounded `EXPERT MODE` block; an unknown name → generic. |
| 11 | Orchestrator wiring — `self.engines` opt-in; `ENGINE` event + expert-mode context at `INTERPRETING`; `test_cmd` surfaced to the Planner. Integration: a Godot fixture task gets an `EXPERT MODE` block in the Planner prompt and an `ENGINE` event with `test_cmd`. |
| 12 | Regression; `milestone_b/MILESTONE_N_NOTES.md`; update [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the top-level [README.md](README.md); rehash `MANIFEST.json`; commit. |

## 6. Acceptance criteria

Gate order: UNIT → INTEGRATION → FAILURE → SECURITY → RECOVERY → BENCHMARK.

- **Unit** — each adapter's `detect()` returns high confidence on its own fixture and ~0 on
  the others; `info()` fills `source_globs` / `build_cmd` / `test_cmd` / `conventions` for
  each engine; `GenericAdapter` picks the right `test_cmd` per ecosystem and always detects
  at a low floor; `EngineRegistry.detect` returns the most specific adapter and never
  returns nothing; `profiles.render` emits a bounded block with `do` / `dont` bullets; a
  `"expert: security-review"` constraint selects that profile.
- **Integration** — with `orch.engines` wired, a Godot-fixture task's Planner prompt contains
  an `EXPERT MODE` block and a `ENGINE` context line, and an `ENGINE` event records the
  engine + `test_cmd`; a plain Python repo detects `generic` and the profile is neutral;
  engines unset → the planning context is byte-identical to Milestone M.
- **Failure** — a malformed `project.godot` / truncated `*.uproject` still detects the engine
  (glob-based) and `info()` degrades the missing fields to defaults, no crash; an
  unreadable workspace → `generic` with empty commands.
- **Security** — detection performs no write and runs no engine binary; the expert profile is
  static text (no injection surface); an `ENGINE` `test_cmd` is data surfaced to the Planner,
  never executed by the orchestrator.
- **Recovery** — `reconcile()` + `resume()` unaffected; detection re-runs on resume (cheap,
  derived).
- **Benchmark** — n/a.

## 7. Tunable starting values

- `ENGINE_MIN_CONF` = **0.6** to auto-enable expert mode; a `"expert: <name>"` constraint
  forces it at any confidence.
- Godot detect: `project.godot` = 0.7, `+0.15` if any `*.gd`, `+0.15` if any `*.tscn`.
- Unreal detect: `*.uproject` = 0.8, `+0.2` if any `*.Build.cs`.
- Android detect: `settings.gradle*` + manifest = 0.85; `com.android.application` string
  in a `build.gradle` = 0.7.
- Generic floor = 0.05.
- `EXPERT MODE` block ≤ 12 lines.

## 8. Risks

- **Detection heuristics drift** — engine project layouts change across versions. Mitigate:
  detection is glob + a couple of string checks (robust), `version_hint` is best-effort, and
  a wrong guess only changes prompt context, never behaviour.
- **Expert profiles go stale** — engine idioms evolve. They are short, static, and easy to
  edit; keeping them terse limits the blast radius of a stale line.
- **`test_cmd` is not run** — a user may expect engine-native verification. Clearly a
  documented tier-C seam; the command is surfaced so a human / CI can run it, and a pytest T0
  still gates when present.
- **Generic over-fires** — with a floor of 0.05 it always matches; the registry only returns
  it when nothing more specific clears its threshold, so it never shadows a real engine.
- **Profile ≠ capability** — expert mode is guidance, not a new tool. It does not grant the
  Builder engine tooling; that is the deferred toolchain work.

## 9. Deliverables

- `app/services/engines/` — `base.py`, `registry.py`, `godot.py`, `unreal.py`,
  `android.py`, `generic.py`, `profiles.py`.
- `EngineInfo` / `ExpertProfile` schemas; `ENGINE` event kind.
- Orchestrator: opt-in `EngineRegistry`; expert-mode context + `ENGINE` event at
  `INTERPRETING`; `test_cmd` surfaced to the Planner.
- Test suite: the current 369 green, plus unit (detect / info / profiles / registry) and
  integration (engine context at planning).
- `milestone_b/MILESTONE_N_NOTES.md`.
- [IMPLEMENTATION_STATUS.md](02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md), the
  [connective index](02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md), and the
  top-level [README.md](README.md) updated: "Windows / Android / Godot / Unreal" moves to
  FOUNDATION for the adapters + expert-profile context; engine-native build/test execution
  is the documented tier-C seam.
