# Slice Findings — Milestone B premise test

The loop under test: **AgentSDKLLM** (Interpreter + Planner, Claude Pro subscription via the
Agent SDK) → **AgentSDKBuilder** (Builder) → **VerifierT0** running pytest in the **Docker
Tier-A sandbox**. No API key, no per-token spend.

Two runs: 10 hand-seeded single-function bugs, then 5 **real** bug-fix commits from
`more-itertools` history (source fix reverted, the test the fix added kept).

## Run 1 — 10 seeded bugs

| id | state | T0 | s | diff_correct |
|---|---|---|---|---|
| 01-pagination-off-by-one | COMPLETED | pass | 21.8 | yes — removed `+ 1` |
| 02-boundary-operator | COMPLETED | pass | 19.2 | yes — `>` → `>=` |
| 03-missing-empty-guard | COMPLETED | pass | 24.9 | yes — `if not xs: return 0.0` |
| 04-int-vs-float-division | COMPLETED | pass | 24.9 | yes — `//` → `/` |
| 05-mutable-default-arg | COMPLETED | pass | 21.6 | yes — `tags=None` + guard |
| 06-wrong-dict-key | COMPLETED | pass | 20.6 | yes — `'town'` → `'city'` |
| 07-inverted-boolean | COMPLETED | pass | 22.6 | yes — dropped the `not` |
| 08-missing-normalization | COMPLETED | pass | 21.6 | yes — `strip().lower()` scan (verbose, correct) |
| 09-accumulator-init | COMPLETED | pass | 18.9 | yes — `0` → `1` |
| 10-returns-first-not-all | COMPLETED | pass | 40.2 | yes — accumulate into a list |

**10/10 completed, 10/10 T0 pass, 10/10 diffs correct.**

## Run 2 — 5 real more-itertools bug fixes

| id | state | T0 | s | diff_correct | note |
|---|---|---|---|---|---|
| mit-01-chunked-negative | FAILED | **fail** | 26.1 | **no** | raised `ValueError('n must be non-negative.')`; the test uses `assertRaisesRegex(..., "n must be at least 0", ...)` — behaviour right, exact message wrong. **T0 correctly rejected it.** |
| mit-02-interleave-evenly-empty | COMPLETED | pass | 26.7 | yes | `if not dims: return` — **identical to the real fix** |
| mit-03-numeric-range-reversed-empty | COMPLETED | pass | 30.9 | yes | empty-range guard in `__reversed__` |
| mit-04-product-index-iterator | COMPLETED | pass | 36.5 | yes | `len(element)` → `len(elements)` — **the real fix** (materialise the iterator before `len`) |
| mit-05-running-min-max-stability | COMPLETED | pass | 66.8 | yes | pop condition `not a < value` → `a > value` — **logically equivalent to the real fix** (keep equal values → stable) |

**4/5 completed with T0 pass; the 1 failure was caught by verification, not shipped.**

## Combined verdict (MILESTONE_B_PLAN.md §7)

- diff_correct: **14 / 15 (93%)**
- **Zero false positives** — nothing incorrect ever reached `COMPLETED`; the one wrong fix
  failed the T0 gate and the task ended `FAILED`.
- unaided T0 criterion: **15 / 15** — the Interpreter always produced a usable pytest target.
- median wall-clock: ~22 s (seeded), ~31 s (real, larger codebase).

**Well above the ≥ 70% threshold → the premise holds.** The loop — request → contract →
plan → edit → sandboxed verify → result — works end to end with a real model and the real
control plane, on real code, and the verification gate reliably distinguishes a passing fix
from a non-passing one.

## Weakness surfaced (actionable, not a blocker)

The Builder does not reliably **read the failing test before editing** — mit-01's fix was
behaviourally correct but didn't match the test's exact `assertRaisesRegex` message. This is
a DESIGN_TIGHTENING §14.1 prompt-tuning item ("make exactly what the test asserts pass"),
addressed later, not a design flaw. Notably the system failed *safely*: T0 caught it.

## Caveats

- Seeded bugs are 1–5 line single-function fixes. The real bugs are small too (1–15 line
  source diffs) though in a genuine codebase with a 7000-line test file.
- Every request named its failing test (realistic bug-report framing; vaguer asks correctly
  route to `WAITING_FOR_USER`).
- Token cost not reported on subscription auth (`0` in the raw tables).
- No personal repos were available on this machine; the "real" run uses open-source history
  as the substitute, which is arguably a stronger signal (bugs not designed by us).

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
