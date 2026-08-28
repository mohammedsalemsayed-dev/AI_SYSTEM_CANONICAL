# Milestone N notes — what is real, what remains

Status against [../MILESTONE_N_PLAN.md](../MILESTONE_N_PLAN.md). **376 tests green.**
All 12 days built. Fifth §10.2 capability domain.

## Real after Milestone N

| Area | Module | Notes |
|---|---|---|
| Adapter contract | `app/services/engines/base.py` | `EngineAdapter` protocol (`name`, `detect(root)->0..1`, `info(root)->EngineInfo`, `expert_profile()->ExpertProfile`). `EngineInfo{engine, version_hint, source_globs, asset_globs, build_cmd, test_cmd, entrypoints, conventions, confidence}`. `ExpertProfile{name, prompt, do[], dont[]}`. `render_profile()` → a ≤ 12-line `EXPERT MODE` block + an `ENGINE:` line with the verify command. |
| Godot | `engines/godot.py` | detect `project.godot` (0.7) + `*.gd` (+0.15) + `*.tscn` (+0.15); `version_hint` from `config/features` / `config_version`; `test_cmd = godot --headless --run-tests`; conventions (snake_case, signals over polling, `@onready`). |
| Unreal | `engines/unreal.py` | detect `*.uproject` (0.8) + `*.Build.cs` (+0.2); modules + `EngineAssociation` from the `.uproject` JSON; `test_cmd` = `UnrealEditor-Cmd … Automation RunTests`; conventions (A/U/F/E/I prefixes, `UPROPERTY`/`UFUNCTION`, gameplay in game modules). |
| Android | `engines/android.py` | detect `settings.gradle*` + `AndroidManifest.xml` (0.9), or `com.android.application` in a `build.gradle` (0.7); modules from `include(...)`; `compileSdk` → `version_hint`; `test_cmd = ./gradlew testDebugUnitTest connectedCheck`; conventions (ViewModel not Activity, res/ not hardcoded). |
| Generic | `engines/generic.py` | always `detect → 0.05`; `info()` sniffs `pyproject.toml` / `package.json` / `go.mod` / `Cargo.toml` / `pom.xml` / `build.gradle` → the ecosystem's `build_cmd` / `test_cmd` (`pytest -q`, `npm test`, `go test ./...`, `cargo test`, `mvn test`, `./gradlew …`); neutral "match the surrounding code" profile. |
| Registry | `engines/registry.py` | `EngineRegistry.detect(root) -> (adapter, EngineInfo)` = highest confidence, ties → most specific (generic last), a broken adapter can't sink detection, **never returns nothing**. `for_name()`. |
| Domain profiles | `engines/profiles.py` | `systems` / `data-pipeline` / `web-frontend` / `security-review` `ExpertProfile`s, selectable by a `"expert: <name>"` entry in `contract.constraints` or the request text. `domain_profile()` / `profile_from_constraints()`. |
| Orchestrator wiring | `orchestrator._engine_context` | `self.engines` opt-in. At `INTERPRETING`: `detect(workspace_path)`; if `confidence ≥ 0.6` **or** a `"expert:"` hint is in the request, prepend the rendered `EXPERT MODE` block (+ the `ENGINE` line) to the listing the Interpreter + Planner see; log an `ENGINE` event `{engine, confidence, version_hint, build_cmd, test_cmd, profile}`. The `test_cmd` is **data surfaced to the Planner**, never executed. Engines unset, or a low-confidence generic repo → no block, no event, byte-identical planning context. |
| Event kind | `ENGINE` (engine, confidence, build/test cmd, profile). |

## Security / scope posture

- Detection is **read-only** (globs + a couple of string checks over workspace files,
  `workspace` trust). No write, no engine-binary invocation.
- Expert profiles are **static text** — no injection surface, no capability grant. Expert
  mode is *guidance*, not a new tool.
- The `ENGINE` `test_cmd` is logged and shown to the Planner as "the engine-native check a
  human/CI would run"; the orchestrator never runs it. A pytest T0, when the contract names
  one, still gates `COMPLETED` unchanged.
- No state-machine, policy, capability, or T-ladder change — this milestone only enriches the
  planning *context* and records a command.

## Not yet real / deferred

- **Engine toolchain execution** — running `godot --headless` / UnrealBuildTool / `gradlew`
  needs the toolchain and a heavier sandbox (§5-C tier C). N ships the command + the seam;
  the run is deferred. Engine-native verification as a T-ladder tier is future work.
- **Engine-language parsers** — J's repo intelligence still uses Python `ast` + a regex
  fallback; a GDScript / Unreal-C++ AST is a J follow-up. Adapters read text project files,
  not `.uasset` / `.tscn` internals beyond globs.
- **More engines** — Unity, Bevy, Xcode/iOS, Flutter, Web (Vite/Next) are additive: a new
  `EngineAdapter` + profile.
- **Asset pipelines** (import / cook / bake) — never in the slice.
- **Version-specific idioms** — `version_hint` is best-effort; profiles are version-agnostic
  and terse to limit staleness.

## Deferred past N (unchanged)

Automated model selection (§10.2 domain 6, needs G + ≥ 20 verified runs — the last §10.2
domain); engine-toolchain sandbox (tier C); per-engine repo-intelligence parsers.
