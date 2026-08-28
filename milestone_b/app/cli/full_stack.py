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
                    verbose: bool = True) -> list[str]:
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
    orch.brainstorm = Brainstorm(lllm)
    orch.critic = Critic(lllm)
    orch.verifier_t2 = VerifierT2(lllm)
    wired += ["brainstorm", "critic", "verifier_t2"]

    # --- research pipeline (research_web + the ladder research rung) --- #
    researcher = Researcher(lllm, EgressBroker(allowlist=[]))
    orch.researcher = researcher
    orch.research = ResearchPipeline(researcher, lllm)
    wired += ["researcher", "research_pipeline"]

    if verbose:
        print("full stack wired: " + ", ".join(wired))
    return wired
