# Active Decisions and Superseded Alternatives

> **Cross-reference**
> - Role: D1–D18 active decisions vs. rejected alternatives, with rationale.
> - Authority: Authoritative; append-only. A superseded alternative is kept for rationale only.
> - Upstream (consumes): Complete Claude-Code Spec, Master Blueprint.
> - Downstream (depended on by): each D-id is referenced from the requirement it governs in [REQUIREMENT_TRACEABILITY.md](../../../../02_CONTEXT_AND_TRACEABILITY/REQUIREMENT_TRACEABILITY.md).
> - Wiring & concrete detail: [DESIGN_TIGHTENING.md](../../../../DESIGN_TIGHTENING.md) — §9 turns D1 into a decision procedure, §4 wires D7/D15 together, §8 sets the D5/D8 promotion gates.

| ID | Active decision | Rejected/superseded alternative | Why |
|---|---|---|---|
| D1 | Small specialized agents with independent challenge | One giant agent or uncontrolled swarm | Specialization helps only when measurable; swarms add latency and fake consensus |
| D2 | Comprehensive architecture + vertical-slice implementation | Disconnected prototypes or years of isolated phases | Full design can exist while implementation proves it end-to-end |
| D3 | Meaningful-progress/stall detection | Fixed timeout for every operation | Long work can be legitimate; evidence distinguishes work from looping |
| D4 | Retry similarity and failure tracking | Endless repair attempts | Repeated actions can consume power/time without objective progress |
| D5 | Controlled experience lifecycle | Blind self-learning | Successful behavior can be stale, unsafe, or overfit |
| D6 | Hierarchical memory and retrieval | One summary replacing history | Canonical evidence must remain recoverable |
| D7 | Strategic local/cloud routing | Cloud banned or always preferred | Quality, privacy, latency, cost and hardware differ by task |
| D8 | Learn from validated cloud outputs/strategies | Copy hidden reasoning | Only observable outputs and evidence are trustworthy artifacts |
| D9 | Independent agent identities + shared canonical state | One shared agent mind | Diversity and challenge are valuable |
| D10 | Futuristic application UI | Terminal/CMD-first UI | User experience should be collaborative and usable |
| D11 | Ask focused questions on material ambiguity | Always guess or constantly interrupt | Balance autonomy with correctness |
| D12 | Capability + execution-boundary security | Folder-only restriction | Path scope alone does not stop broader authority |
| D13 | Modular monolith | Premature microservices | Reduces complexity while preserving explicit boundaries |
| D14 | Intent/prompt compilation subordinate to original request | Prompt engineer silently rewriting goals | Preserve user intent and traceability |
| D15 | Hardware/power-aware scheduling | Ignore component health | Sustained load and trends matter |
| D16 | Autonomous internet research with evidence | File-only knowledge | Research is a required capability |
| D17 | Empirical model selection | Permanent architecture model names | Target hardware and workloads decide |
| D18 | Add architecture only for demonstrated gaps | Endless subsystem expansion | Implementation/testing should now drive changes |
