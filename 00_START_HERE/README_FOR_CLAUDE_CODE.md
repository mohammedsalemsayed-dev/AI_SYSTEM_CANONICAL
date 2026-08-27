# START HERE — CANONICAL COMPLETE PACKAGE

> **Cross-reference**
> - Role: Entry point — read order and authority rules.
> - Authority: Navigation aid; does not override the Complete Claude-Code Spec.
> - Upstream (consumes): none.
> - Downstream (depended on by): every document in this package.
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../DESIGN_TIGHTENING.md) — whole document; the document map is §13.

This ZIP is the canonical context package for implementing the Autonomous Hardware-Aware Multi-Agent AI System.

## Read this package in order
1. `README_FOR_CLAUDE_CODE.md` (this file)
2. `../01_AUTHORITATIVE_SOURCE_DOCUMENTS/Autonomous_Multi_Agent_AI_System_Complete_Claude_Code_Spec.docx`
3. `../01_AUTHORITATIVE_SOURCE_DOCUMENTS/Autonomous_Multi_Agent_AI_System_Master_Blueprint.docx`
4. `../01_AUTHORITATIVE_SOURCE_DOCUMENTS/Pasted text.txt`
5. `../02_CONTEXT_AND_TRACEABILITY/CANONICAL_CONTEXT.md`
6. `../02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md`
7. `../02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md`
8. `../03_IMPLEMENTATION_FOUNDATION/`
9. `../04_ACCEPTANCE_AND_GOVERNANCE/`

## Authority
The Complete Claude-Code Spec is the primary authoritative source.
The Master Blueprint provides architectural rationale and professional evaluation.
The pasted requirements preserve broader product capabilities that must not silently disappear.
The context and traceability files are navigation/reconciliation aids; they do not override an explicit final decision in the authoritative specification.

## Non-negotiable rule
Do not treat a summary as a replacement for the authoritative documents.
Do not silently drop a requirement because it is not yet implemented.
Do not confuse "planned" or "foundation" with "complete."

## What to build
A modular-monolith desktop AI workstation where specialized agents can reason and challenge each other while deterministic services own:
state, permissions, execution boundaries, verification, recovery, memory trust, controlled learning, hardware protection, and model routing.

## First implementation rule
Build through integrated vertical slices, but preserve the complete architecture. A phase is an implementation order, not permission to forget later requirements.

## Before every substantial change
- Read the relevant authoritative section.
- Identify affected contracts and requirements.
- Inspect existing implementation.
- Preserve original user objective and active decisions.
- Update tests and traceability.
- Do not bypass security or verification for convenience.
