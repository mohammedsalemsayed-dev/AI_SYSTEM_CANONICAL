# Claude Code Operating Protocol


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
12. Update requirements.md when a requirement moves from NOT IMPLEMENTED → FOUNDATION → IMPLEMENTED/VERIFIED.

Definition of done:
- contract satisfied;
- relevant tests pass;
- failure behavior known;
- security boundaries intact;
- artifacts/events/checkpoints recorded where required;
- independent verification succeeds when required;
- traceability updated.
