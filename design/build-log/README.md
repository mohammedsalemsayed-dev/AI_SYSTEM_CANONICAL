# build-log

The day-by-day record of building NEXUS: a `MILESTONE_*_PLAN.md` I wrote before
each stage, a `MILESTONE_*_NOTES.md` written after it saying what actually landed
versus what stayed a stub, plus the benchmark and findings write-ups.

Kept for an honest account of how the project was made — I wrote the plans and
drove Claude Code through them, reviewing diffs and running the tests as the gate.
None of this is needed to understand or use the system; for that, read the root
[README](../../README.md) and [../STATUS.md](../STATUS.md).

The stage letters are just build order. They don't map to anything in the code.

- Benchmarks: `BUILDER_BENCH.md` (local models on seeded bugs),
  `LOCAL_FIRST_BENCH_REAL.md` (full pipeline on real library bugs),
  `LOCAL_FIRST_BENCH.md`, `REAL_RUN_FINDINGS.md`.
- Other findings: `SLICE_FINDINGS.md`, `FAULT_FINDINGS.md`, `POSTGRES_NOTES.md`.
- `final-reconciliation.md` — why the original spec package was repackaged.
