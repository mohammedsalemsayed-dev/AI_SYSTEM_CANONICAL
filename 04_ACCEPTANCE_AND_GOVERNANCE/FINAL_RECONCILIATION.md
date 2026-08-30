# Final Reconciliation

> **Cross-reference**
> - Role: Explains the packaging correction and the scope-preservation rule.
> - Authority: Context.
> - Upstream (consumes): none.
> - Downstream (depended on by): [REQUIREMENT_TRACEABILITY.md](../02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md).
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../DESIGN_TIGHTENING.md) — §10 keeps every listed requirement in scope, sequenced by prerequisite rather than dropped; §13 document map.

This package corrects the previous packaging failure.

The prior final ZIP compressed a large body of authoritative requirements into a smaller scaffold and summary. That made it possible for an implementation agent to miss requirements such as:
- whole-repository intelligence;
- explicit coding autonomy levels;
- Git lifecycle;
- broad development tool domains;
- research/RAG;
- document and presentation generation;
- ~~expert modes~~ — later dropped by explicit decision (2026-08-30): the engine-adapter /
  expert-mode layer was built and removed as not worth the complexity. See the root
  [README.md](../README.md) and [IMPLEMENTATION_STATUS.md](../02_CONTEXT_AND_TRACEABILITY/IMPLEMENTATION_STATUS.md);
- complete provider/benchmark implementation.

The authoritative source documents are therefore preserved verbatim in this package. The traceability files explicitly distinguish active requirements from implemented code.

If a requirement appears in the authoritative Complete Claude-Code Spec or preserved broader product requirements and is not superseded by a newer explicit decision, it remains active.
