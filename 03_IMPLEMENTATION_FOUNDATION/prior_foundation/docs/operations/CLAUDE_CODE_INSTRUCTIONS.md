# Instructions for Coding Agents

> **Cross-reference**
> - Role: Working rules for a coding agent implementing this predesigned system.
> - Authority: Operational; subordinate to the authority documents.
> - Upstream (consumes): [README.md](../../README.md), [00_MASTER_SPEC.md](../00_MASTER_SPEC.md).
> - Downstream (depended on by): none.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../../../../DESIGN_TIGHTENING.md) — §5 makes "independent verification" concrete (tiers T0–T3), §2 lists the component interfaces to preserve.

You are implementing a predesigned system.

Before changing code:
1. Read README and authority documents.
2. Identify the active milestone.
3. Read relevant contracts and tests.
4. Inspect existing code before structural changes.
5. Preserve contracts unless explicitly changed.

Never:
- bypass policy/capability checks;
- broaden filesystem access for convenience;
- replace deterministic controls with prompts;
- silently reinterpret the original objective;
- endlessly retry similar fixes;
- add speculative abstractions with no current use.

Always:
- record assumptions;
- make the smallest compatible change;
- add/update tests;
- run relevant tests;
- report changed files, evidence, failures, and remaining uncertainty.

Definition of done:
contract implemented + tests pass + failure behavior known + boundaries intact + required events/artifacts recorded + independent verification where required.
