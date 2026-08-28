# Real-run findings — first end-to-end runs against real models

Date: 2026-08-28. Machine: Windows 10, RTX 5060 (8 GB VRAM), Python 3.14.
Nothing here is scripted — real Claude (subscription / Agent SDK) and a real local
model (Ollama) drove the pipeline; T0 verification ran in the `slice-sandbox:pytest`
Docker container.

## Task

Fresh scratch git repo. `strutil.py::slugify` handled only the trivial case;
`test_strutil.py` had 2 failing tests (strip punctuation, collapse repeated
separators) + 1 passing.

Request: *"Fix slugify() … The failing tests are
test_strutil.py::test_strips_punctuation and
test_strutil.py::test_collapses_repeated_separators."*

## Run 1 — cloud (SLICE_LLM=agent_sdk, subscription auth, no token spend)

| Stage | Result |
|---|---|
| Interpreter | real contract, correct objective |
| Planner | 1-step plan |
| Builder (`AgentSDKBuilder`, headless Claude) | wrote a **correct** fix: `import re`; lowercase→hyphenate; `re.sub(r"[^a-z0-9-]", "", …)`; `re.sub(r"-+", "-", …)`; `.strip("-")` |
| VerifierT0 | applied the diff to a clean checkout, ran pytest **in Docker** → all 3 pass |
| Final state | **COMPLETED, verified=True** |

The full control plane — interpret → plan → capability grant → policy check →
sandboxed verify → state machine — ran on real models and produced the right
answer. **The premise holds.**

## Run 2 — local Interpreter+Planner (SLICE_LLM=local, `qwen2.5-coder:7b` on Ollama), cloud Builder

| Stage | Result |
|---|---|
| Interpreter (`qwen2.5-coder:7b`, 100% GPU) | clean contract, 441 in / 218 out tokens, 3.6 s |
| Planner (`qwen2.5-coder:7b`) | **4-step plan with conditional / verification pseudo-steps** ("Run the test for stripping punctuation", "Edit … *if the test fails*", "Understand the failing tests") |
| Execution | step 1's edit actually flipped the tests green (`acceptance_flip`), but the junk trailing steps produced no new hard-progress signal |
| Loop detection (Milestones D + U) | flagged `LOOP_RISK` after 2 no-progress steps; escalation ladder re-planned (6 steps, also degenerate), same pattern; after 4 `LOOP_RISK` escalations → escalated to the user |
| Final state | **WAITING_FOR_USER** — "loop_risk after escalation ladder: no hard-progress signal" |

This is the safety machinery working correctly on a real run: no false
`COMPLETED`, no infinite spin, a coherent escalation with a clarification question.

## Run 3 — write-back (SLICE_LLM=agent_sdk, `run_task --apply`)

Same task. `COMPLETED, verified=True` → `apply_task_result` wrote the verified
diff back to the real `strutil.py` → `3 passed` when the tests are run directly.
The system now *fixes* code, not just *validates a proposed fix*.

## Run 4 — dual local model (`--interpreter-llm local:llama3.1:8b --planner-llm local:llama3.1:8b`, cloud Builder, `--apply`)

| Stage | Result |
|---|---|
| Interpreter (`llama3.1:8b`, GPU) | clean contract, 442 in / 135 out, 6.8 s |
| Planner (`llama3.1:8b`) | **2 clean steps**: (1) modify `slugify()` `[fs.write]`, (2) run pytest `[shell.run]` — **no "edit the test" step** (the guarded Planner prompt held) |
| Execution | both steps `HEALTHY_PROGRESS` — **no `LOOP_RISK`**, unlike `qwen2.5-coder:7b` |
| VerifierT0 | pass (Docker) → **COMPLETED, verified=True** → applied to `strutil.py` → `3 passed` |

`llama3.1:8b` is a materially better local Planner/Interpreter for this system
than `qwen2.5-coder:7b`. The raw-prompt worry ("edit the test file") did **not**
happen through the real `Planner` class. Model allocation: `llama3.1:8b` for
`local-small` / `local-reasoner` (interpret / plan / reason);
`qwen2.5-coder:7b` for `local-coder` (code_edit_local / debug).

## Bugs / gaps surfaced

1. **The verified fix is never written back.** **FIXED** — `app/services/build/apply.py`
   `apply_task_result()` + `run_task --apply` (Runs 3 & 4). The Orchestrator still
   never touches the user's tree; applying is a separate, verification-gated,
   `APPLIED`-logged step.

2. **Token accounting on the `agent_sdk` path.** `claude_agent_sdk` 0.2.145
   returns `ResultMessage.usage` as a **dict**, not an object; `AgentSDKLLM` used
   `getattr(usage, "input_tokens", 0)` → always 0. **Status: partially fixed** —
   output tokens now captured; input tokens are split across
   `input_tokens` + `cache_read_input_tokens` + `cache_creation_input_tokens`
   with prompt caching and are now summed, but the SDK's reporting of the
   pre-cache prompt size is still approximate.

3. **`qwen2.5-coder:7b` is a weak Planner.** Emits conditional pseudo-steps that
   trip the (correctly functioning) stall detector. **Resolved by model choice:**
   `llama3.1:8b` plans cleanly (Run 4). Keep `qwen2.5-coder:7b` for
   `code_edit_local` / `debug`, `llama3.1:8b` for interpret / plan / reason.

4. **`.gitignore` hid the Builder package.** Line 8 `build/` also matched
   `milestone_b/app/services/build/` → `base.py` / `fake.py` / `agent_sdk.py` /
   `workspace_copy.py` were never committed in any milestone; a fresh clone would
   fail at import. **FIXED** (`/build/` anchored; files recovered — commit
   `6fbfc94`).

## What was wired

- `app/llm/local_llm.py` — `OllamaLLM` (stdlib `urllib`, no new dependency);
  `available()` health check; returns real `prompt_eval_count` / `eval_count`.
- `app/llm/__init__.py` — `get_llm("local")` / `get_llm("ollama")`.
- `app/llm/agent_sdk_llm.py` — dict-shaped `usage` handling (fix #2).
- `app/services/routing/registry.py` — `local-coder` now names the real model
  (`qwen2.5-coder:7b`), still `available=False` in the seed; new
  `ProviderRegistry.probe_local()` flips it to available at runtime iff an Ollama
  server answers with the model pulled. Seed stays a seam; a run on a machine
  without Ollama is unchanged.

Env knobs: `OLLAMA_HOST` (default `http://localhost:11434`), `OLLAMA_MODEL`
(default `qwen2.5-coder:7b`). Run with the local tier:
`python -m app.cli.run_task "<req>" --workspace <repo> --llm local --builder agent_sdk`.
