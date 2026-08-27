# Claude Code Operating Protocol

> **Cross-reference**
> - Role: Per-change protocol and definition of done for the implementing agent.
> - Authority: Operational governance; subordinate to the authoritative documents.
> - Upstream (consumes): [README_FOR_CLAUDE_CODE.md](../00_START_HERE/README_FOR_CLAUDE_CODE.md), [CLAUDE_CODE_INSTRUCTIONS.md](../03_IMPLEMENTATION_FOUNDATION/prior_foundation/docs/operations/CLAUDE_CODE_INSTRUCTIONS.md).
> - Downstream (depended on by): none.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../DESIGN_TIGHTENING.md) — §5 "independent verification" as tiers T0–T3; item 12 targets the connective index in §13.

1. Read the package in the required order.
2. Treat authoritative documents as requirements, not inspiration.
3. Determine the current vertical slice and affected requirement IDs.
4. Inspect code before editing.
5. Make the smallest compatible implementation change.
6. Preserve contracts and original user intent.
7. Never bypass deterministic policy, capability or verification boundaries.
8. Never broaden filesystem/host authority merely to make implementation easier.
9. Do not endlessly retry similar repairs; use the progress/loop protocol.
10. Add or update tests with every meaningful implementation change.
11. Report: changed files, requirement coverage, tests run, evidence, failures and remaining uncertainty.
12. Update REQUIREMENT_TRACEABILITY.md when a requirement moves from NOT IMPLEMENTED → FOUNDATION → IMPLEMENTED/VERIFIED.

Definition of done:
- contract satisfied;
- relevant tests pass;
- failure behavior known;
- security boundaries intact;
- artifacts/events/checkpoints recorded where required;
- independent verification succeeds when required;
- traceability updated.
