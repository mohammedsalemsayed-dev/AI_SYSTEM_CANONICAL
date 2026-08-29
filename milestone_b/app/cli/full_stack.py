"""Wire the complete agent roster onto an Orchestrator (`run_task --full`).

Everything the design lists, connected in one place:

  Interpreter / Planner        local model (set by run_task's --llm / --local)
  Builder                      local-first (LocalBuilder) + cloud fallback
  builder_registry + Router    route decision can pick the Builder per task_class;
                               Router also logs ROUTE, does the hardware pause,
                               and feeds RouteStatsStore for later data-driven picks
  Critic                       on (local) — positioned so it can't false-reject T0
  Independent Verifier (T2)    on (local) — advisory ensemble
  Research pipeline            on (local) — research_web tasks + the ladder rung
  Memory + Experience          on (file-backed) — context + the learning lifecycle
  RolePerformance              on — shadow metrics per role
  Policy / Hardware / Progress  already deterministic in the core

Deterministic-by-design (no LLM): Model Router, Hardware Scheduler, Policy Engine,
Progress/Loop Detector. Not built: a dedicated Creative/Brainstorming agent.
"""

from __future__ import annotations

from pathlib import Path


def wire_full_stack(orch, *, local_model: str = "qwen3:8b", db_path: str = "slice_events.db",
                    workspace: str | None = None, t2_on_cloud: bool = True,
                    per_file_policy: bool = True, verbose: bool = True) -> list[str]:
    """Attach every optional agent to `orch`. Returns a list of what was wired."""
    from app.llm import get_llm
    from app.services.agents.brainstorm import Brainstorm
    from app.services.agents.critic import Critic
    from app.services.agents.performance import RolePerformanceStore
    from app.services.agents.researcher import Researcher
    from app.services.build import get_builder
    from app.services.egress.broker import EgressBroker
    from app.services.experience.store import ExperienceStore
    from app.services.memory.store import MemoryStore
    from app.services.research.pipeline import ResearchPipeline
    from app.services.routing.registry import ProviderRegistry
    from app.services.routing.router import Router
    from app.services.routing.stats import RouteStatsStore
    from app.services.tools.adapters.egress_tool import EgressToolAdapter
    from app.services.tools.adapters.engine_tool import EngineToolAdapter
    from app.services.tools.adapters.fs_tool import FsToolAdapter
    from app.services.tools.adapters.git_tool import GitToolAdapter
    from app.services.tools.adapters.shell_tool import ShellToolAdapter
    from app.services.tools.registry import ToolRegistry
    from app.services.verify.verifier_t2 import VerifierT2

    wired: list[str] = []
    local = f"local:{local_model}"
    lllm = get_llm(local)

    # --- memory + experience (file-backed, alongside the event db) -------- #
    base = Path(db_path)
    mem = MemoryStore(str(base.with_suffix(".memory.db")))
    orch.memory = mem
    orch.experience = ExperienceStore(str(base.with_suffix(".experience.db")))
    orch.role_perf = RolePerformanceStore(mem)
    wired += ["memory", "experience", "role_perf"]

    # --- Router + provider registry (local-aware) ----------------------- #
    reg = ProviderRegistry()
    enabled = reg.probe_local()
    stats = RouteStatsStore(mem)
    orch.router = Router(reg, stats, seed=0)
    orch.route_stats = stats
    wired.append(f"router (local providers: {enabled or 'none — Ollama down'})")

    # --- builder registry: route decision -> Builder ------------------ #
    cloud_builder = get_builder("agent_sdk")
    local_builder = get_builder(local)  # LocalBuilder(local_model)
    orch.builder_registry = {
        "local-coder": local_builder, "local-small": local_builder,
        "local-reasoner": local_builder, "local": local_builder,
        "agent_sdk": cloud_builder, "anthropic": cloud_builder,
    }
    # local-first regardless of what the static table currently prefers:
    if enabled:
        orch.builder = local_builder
    orch.fallback_builder = cloud_builder
    wired.append("builder_registry + local-first + cloud fallback"
                 if enabled else "builder = cloud (Ollama down)")

    # --- Creative agent (pre-plan) + Critic + T2 verifier (advisory) -- #
    # An independent verifier is only worth its cost if it is a *different,
    # stronger* judge than the Builder. A local 8B T2 is noisy (it false-flags
    # correct diffs — see LOCAL_FIRST_BENCH.md), so T2 runs on cloud by default.
    t2_llm = get_llm("agent_sdk") if t2_on_cloud else lllm
    orch.brainstorm = Brainstorm(lllm)
    orch.critic = Critic(lllm)
    orch.verifier_t2 = VerifierT2(t2_llm)
    wired += ["brainstorm", "critic",
              "verifier_t2(cloud)" if t2_on_cloud else "verifier_t2(local)"]

    # --- research pipeline (research_web + the ladder research rung) --- #
    researcher = Researcher(lllm, EgressBroker(allowlist=[]))
    orch.researcher = researcher
    orch.research = ResearchPipeline(researcher, lllm)
    wired += ["researcher", "research_pipeline"]

    # --- authoring pipeline (M) — DOCX / PPTX / PDF / MD deliverables ---- #
    from app.services.authoring.pipeline import AuthoringPipeline

    orch.authoring = AuthoringPipeline(lllm)  # renderer chosen per-task from the brief
    wired.append("authoring(docx,pptx,md,html)")

    # --- tool adapter registry (S) — enumerated at planning, policy-gated #
    treg = (ToolRegistry()
            .register(FsToolAdapter())
            .register(ShellToolAdapter())
            .register(EngineToolAdapter())
            .register(EgressToolAdapter(EgressBroker(allowlist=[]))))
    if workspace:
        from app.services.repo.git_adapter import GitAdapter

        try:
            treg.register(GitToolAdapter(GitAdapter(workspace)))
        except Exception:  # noqa: BLE001 — not a git repo / git missing
            pass

        # external MCP servers declared by the project's own .mcp.json
        # (e.g. an Unreal-editor MCP) — registered only when reachable now.
        mcp_json = Path(workspace) / ".mcp.json"
        if mcp_json.is_file():
            from app.services.tools.adapters.mcp_tool import from_mcp_json

            for ad in from_mcp_json(str(mcp_json)):
                if ad.available():
                    treg.register(ad)
                    wired.append(f"{ad.name}({len(ad.manifest().ops)} ops)")
    orch.tools = treg
    wired.append("tools(" + ",".join(a.name for a in treg.all()) + ")")

    # --- engine registry (N) — engine-aware expert context at planning - #
    # detect(root) resolves Godot / Unreal / Android / generic; the orchestrator
    # folds the adapter's expert profile + test command into the planner prompt.
    from app.services.engines.registry import EngineRegistry

    orch.engines = EngineRegistry()
    wired.append("engines(godot,unreal,android,generic)")

    # --- bounded tool-use loop (T) — the `ops` deliverable path -------- #
    # one policy-checked tool call per turn, on a workspace copy. Uses the same
    # ToolRegistry (so project .mcp.json ops are reachable) and Policy Engine.
    from app.services.tools.dispatch import ToolDispatcher
    from app.services.tools.loop import ToolLoop

    _dispatcher = ToolDispatcher(
        treg, orch.policy, risk_globs=getattr(orch.policy, "risk_globs", None)
    )
    orch.tool_loop = ToolLoop(_dispatcher, lllm)
    wired.append("tool_loop")

    # --- fitted model selection (O) — data-driven routing weights ----- #
    # inert until a task_class has >= MIN_ELIGIBLE_MODELS of route history;
    # then the Router consults learned weights instead of the static table.
    from app.services.routing.selection import ModelSelectionController

    orch.selection = ModelSelectionController(mem, stats, reg)
    wired.append("selection")

    # --- knowledge base (L) — persistent doc library for doc_analysis - #
    from app.services.kb.store import KnowledgeBase

    orch.kb = KnowledgeBase(str(base.with_suffix(".kb.db")))
    wired.append("kb")

    # --- §14.1 per-changed-file policy gate (V) — ON in the full stack -- #
    orch.per_file_policy = per_file_policy
    if per_file_policy:
        wired.append("per_file_policy")

    if verbose:
        print("full stack wired: " + ", ".join(wired))
    return wired
