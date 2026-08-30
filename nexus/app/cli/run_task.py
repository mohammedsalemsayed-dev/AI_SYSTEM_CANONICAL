"""CLI entry point for the slice.

    python -m app.cli.run_task "<request>" --workspace <path> [--db events.db]

Defaults to the real providers (Anthropic LLM + Agent SDK builder). Set
SLICE_LLM_MODEL for the model id. For an offline dry run, import the orchestrator
and inject ScriptedLLM / ScriptedBuilder instead (see the tests).
"""

from __future__ import annotations

import argparse
import os
import sys

from app.events.log import EventKind, EventLog, open_event_log
from app.orchestration.orchestrator import Orchestrator
from app.services.build import get_builder
from app.services.interpret.interpreter import Interpreter
from app.services.plan.planner import Planner
from app.services.policy.engine import PolicyEngine
from app.services.verify.verifier_t0 import VerifierT0
from app.services.workspace.listing import is_git_repo
from app.llm import get_llm

_SUMMARY_KEYS = (
    "state", "text", "objective", "overall", "decision", "rule", "token",
    "approved", "reason", "error", "verified",
    "sender", "intent", "verdict", "effective_class", "between",
)


def _summarize(payload: dict) -> str:
    bits = [f"{k}={payload[k]!r}" for k in _SUMMARY_KEYS if k in payload]
    return " ".join(bits) or ", ".join(sorted(payload)[:4])


def print_timeline(log: EventLog, task_id: str) -> None:
    print(f"\n=== timeline for {task_id} ===")
    for event in log.read(task_id):
        print(f"  {event.seq:>3}  {event.kind:<16} {_summarize(event.payload)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_task")
    parser.add_argument("request")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--db", default="slice_events.db",
                        help="event store: a SQLite path (default) or a "
                             "'postgres://user:pass@host/db' URL (needs the "
                             "'postgres' extra). NEXUS_DB_URL overrides this.")
    parser.add_argument("--llm", default=os.environ.get("SLICE_LLM", "anthropic"),
                        help="default provider for every role (agent_sdk | anthropic | local)")
    parser.add_argument("--interpreter-llm", default=None,
                        help="override the Interpreter's provider (default: --llm)")
    parser.add_argument("--planner-llm", default=None,
                        help="override the Planner's provider (default: --llm)")
    parser.add_argument("--critic-llm", default=None,
                        help="override the Critic's provider (default: --llm)")
    parser.add_argument("--builder", default=os.environ.get("SLICE_BUILDER", "agent_sdk"))
    parser.add_argument("--critic", action="store_true", help="run a Critic pass before verify")
    parser.add_argument("--apply", action="store_true",
                        help="on COMPLETED+verified, write the diff back to --workspace")
    parser.add_argument(
        "--local", action="store_true",
        help="convenience: Interpreter + Planner (+ Critic) on local:qwen3:8b; "
             "Builder stays on agent_sdk (cloud). One local model resident, no "
             "VRAM swap. Add --local-builder to run the Builder on qwen3:8b too "
             "(fully local; benchmarked 9/10 on the seeded bug repos).",
    )
    parser.add_argument("--local-builder", action="store_true",
                        help="with --local, run the Builder on local:qwen3:8b (LocalBuilder)")
    parser.add_argument(
        "--fallback-builder", default=None,
        help="if the Builder's diff fails verification, retry ONCE with this "
             "builder (e.g. agent_sdk). Default: agent_sdk when --local-builder is set.",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="wire the COMPLETE agent roster: local-first Builder + cloud "
             "fallback, Router + provider registry, Critic, independent T2 "
             "verifier, research pipeline, memory + experience + role metrics. "
             "Implies --local. Deterministic agents (Router/Hardware/Policy/"
             "Progress) are always on.",
    )
    args = parser.parse_args(argv)

    if args.full:
        args.local = True
    if args.local:
        args.interpreter_llm = args.interpreter_llm or "local:qwen3:8b"
        args.planner_llm = args.planner_llm or "local:qwen3:8b"
        args.critic_llm = args.critic_llm or "local:qwen3:8b"
        if (args.local_builder or args.full) and args.builder in ("agent_sdk", None):
            args.builder = "local:qwen3:8b"
            args.fallback_builder = args.fallback_builder or "agent_sdk"

    workspace = os.path.abspath(args.workspace)
    if not os.path.isdir(workspace):
        print(f"workspace not found: {workspace}", file=sys.stderr)
        return 2
    if not is_git_repo(workspace):
        print(f"workspace must be a git repo: {workspace}", file=sys.stderr)
        return 2

    log = open_event_log(args.db)
    try:
        # one provider instance per distinct kind (a local server is stateful; a
        # cloud client is cheap either way)
        _cache: dict[str, object] = {}

        def _llm(kind: str):
            return _cache.setdefault(kind, get_llm(kind))

        interp_kind = args.interpreter_llm or args.llm
        plan_kind = args.planner_llm or args.llm
        critic_kind = args.critic_llm or args.llm
        print(f"LLM: interpreter={interp_kind} planner={plan_kind} "
              f"builder={args.builder}" + (f" critic={critic_kind}" if args.critic else ""))

        critic = None
        if args.critic:
            from app.services.agents.critic import Critic

            critic = Critic(_llm(critic_kind))
        orch = Orchestrator(
            log,
            Interpreter(_llm(interp_kind)),
            Planner(_llm(plan_kind)),
            get_builder(args.builder),
            VerifierT0(),
            PolicyEngine(),
            critic=critic,
        )
        if args.fallback_builder:
            orch.fallback_builder = get_builder(args.fallback_builder)
            print(f"     fallback builder: {args.fallback_builder} (on verification failure)")
        if args.full:
            from app.cli.full_stack import wire_full_stack

            wire_full_stack(orch, db_path=args.db, workspace=workspace)
        result = orch.run(args.request, workspace)
        print_timeline(log, result.task_id)
        print("\n=== result ===")
        print(result.model_dump_json(indent=2))

        if args.apply:
            from app.services.build.apply import apply_task_result

            ap = apply_task_result(log, result.task_id, workspace)
            print(f"\n=== apply === {ap.reason}"
                  + (f"  ({', '.join(ap.changed_paths)})" if ap.changed_paths else ""))
            if not ap.applied and result.state == "COMPLETED":
                return 1
        return 0 if result.state == "COMPLETED" else 1
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
