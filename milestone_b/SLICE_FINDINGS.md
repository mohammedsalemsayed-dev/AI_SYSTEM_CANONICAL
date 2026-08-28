# Slice Findings — Milestone B premise test

The loop under test: **AgentSDKLLM** (Interpreter + Planner, Claude Pro subscription via the
Agent SDK) → **AgentSDKBuilder** (Builder) → **VerifierT0** running pytest in the **Docker
Tier-A sandbox**. No API key, no per-token spend.

Two runs: 10 hand-seeded single-function bugs, then 5 **real** bug-fix commits from
`more-itertools` history (source fix reverted, the test the fix added kept). The real run was
repeated after the "next steps" step 1 (Builder prompt hardened to read the failing test
first and match its exact assertions).

## Run 1 — 10 seeded bugs

**10/10 completed, 10/10 T0 pass, 10/10 diffs correct** (off-by-one, boundary operator,
empty guard, int/float division, mutable default arg, wrong dict key, inverted boolean,
missing normalization, accumulator init, returns-first-not-all). Median ~22 s.

## Run 2 — 5 real more-itertools bug fixes

### Before step 1 (original Builder prompt)

| id | state | T0 | diff_correct |
|---|---|---|---|
| mit-01-chunked-negative | FAILED | fail | **no** — `ValueError('n must be non-negative.')`; test wants `assertRaisesRegex(..., "n must be at least 0")` |
| mit-02..05 | COMPLETED | pass | yes ×4 |

4/5. The miss: behaviour right, exact message wrong. **T0 correctly rejected it.**

### After step 1 (Builder reads the target test, matches its exact assertions)

| id | state | T0 | s | diff_correct | note |
|---|---|---|---|---|---|
| mit-01-chunked-negative | COMPLETED | pass | 170.0 | **yes** | `raise ValueError('n must be at least 0')` — **now identical to the real fix** |
| mit-02-interleave-evenly-empty | COMPLETED | pass | 36.3 | yes | `if dims == 0: return` |
| mit-03-numeric-range-reversed-empty | COMPLETED | pass | 45.9 | yes | `if len(self) == 0: return iter(())` |
| mit-04-product-index-iterator | COMPLETED | pass | 51.1 | yes | `len(element)` → `len(elements)` — the real fix |
| mit-05-running-min-max-stability | COMPLETED | pass | 229.9 | yes | pop condition `not a < value` → `a > value` — logically equivalent to the real fix |

**5/5.** Wall-clock rose on the two hardest tasks (26 s → 170 s, and 230 s) because the
Builder now reads the test file before editing — a correctness/latency trade to tune later.

## Combined verdict (MILESTONE_B_PLAN.md §7)

- diff_correct: **15 / 15 (100%)** after step 1
- **Zero false positives** across every run — nothing incorrect ever reached `COMPLETED`
- unaided T0 criterion: **15 / 15**

**The premise holds.** The loop works end to end with a real model and the real control
plane, on real code, and the verification gate reliably distinguishes a passing fix from a
non-passing one. The one class of miss (behaviourally-plausible fix that doesn't match a
precise assertion) was closed by a prompt change and is the exact case the Milestone E
Critic is designed to catch structurally.

## Caveats

- Bugs are small (1–15 line source diffs) though the real ones live in a genuine codebase
  with a 7000-line test file.
- Every request named its failing test (realistic bug-report framing; vaguer asks correctly
  route to `WAITING_FOR_USER`).
- Token cost not reported on subscription auth (`0` in the raw tables).
- No personal repos were available on this machine; the "real" run uses open-source history
  as the substitute (bugs not designed by us — arguably a stronger signal).

## Reproduce

```bash
cd milestone_b
python -m tests.premise.make_seeded_repos
python -m tests.premise.run_real_tasks tests/premise/tasks.seeded.json

git clone --depth 250 https://github.com/more-itertools/more-itertools /tmp/mit
python -m tests.premise.make_real_repos /tmp/mit
python -m tests.premise.run_real_tasks tests/premise/tasks.real.json
```
Needs a logged-in `claude` CLI (`claude -p "PONG"` must work).
