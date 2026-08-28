"""Milestone I day 13 — standalone guardrail regression runner
(MILESTONE_I_PLAN.md §2, DESIGN_TIGHTENING §8, §11.2).

Runs the frozen guardrail suite through a real Orchestrator, compares the result
to the stored baseline (system memory), and exits non-zero on a regression
(aggregate drop > 2 pp, or any previously-passing guardrail task now failing).

    pip install -e ".[llm]"
    # first run — record the baseline:
    python -m tests.regression.run_guardrail --set-baseline --memory milestone_b/guardrail.db
    # later runs — gate against it:
    python -m tests.regression.run_guardrail --memory milestone_b/guardrail.db

    # offline smoke path (scripted providers, no model calls):
    python -m tests.regression.run_guardrail --offline

Needs a logged-in `claude` CLI for the real path (subscription via the Agent
SDK), like the premise harness. NOT run against real models in the test suite.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from app.events.log import EventKind, EventLog
from app.schemas.contracts import SuiteResult
from app.services.eval.guardrail import GuardrailSuite, GuardrailTask, materialize
from app.services.eval.regression import RegressionBaseline, check_regression


def _real_run_one(task: GuardrailTask) -> bool:
    from app.llm import get_llm
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.agent_sdk import AgentSDKBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    llm = get_llm("agent_sdk")
    with tempfile.TemporaryDirectory() as tmp:
        repo = materialize(task, Path(tmp) / task.id)
        log = EventLog(":memory:")
        orch = Orchestrator(
            log, Interpreter(llm), Planner(llm), AgentSDKBuilder(),
            VerifierT0(), PolicyEngine(),
        )
        return orch.run(task.request(), repo).verified


def _offline_run_one(task: GuardrailTask) -> bool:
    """Scripted providers + a builder that writes the known oracle. Exercises the
    suite + regression plumbing without any model call."""
    from app.llm.fake import ScriptedLLM
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.sandbox.subprocess_backend import SubprocessSandbox
    from app.services.verify.verifier_t0 import VerifierT0
    from tests.integration.conftest import interpreter_reply, planner_reply

    test_name = f"test_{task.id.replace('-', '_')}.py"
    replies = [
        interpreter_reply(
            objective=f"fix {task.module} so {test_name} passes",
            required_evidence=[f"T0: pytest {test_name} passes"],
        ),
        planner_reply(intent=f"apply the fix to {task.module}"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        repo = materialize(task, Path(tmp) / task.id)
        log = EventLog(":memory:")
        runner = SubprocessSandbox()
        orch = Orchestrator(
            log, Interpreter(ScriptedLLM(replies)), Planner(ScriptedLLM(replies)),
            ScriptedBuilder({task.module: task.fix}), VerifierT0(runner=runner),
            PolicyEngine(), runner=runner,
        )
        return orch.run(task.request(), repo).verified


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="scripted providers, no model calls")
    ap.add_argument("--set-baseline", action="store_true", help="record this run as the baseline")
    ap.add_argument("--memory", default=":memory:", help="sqlite path for the RegressionBaseline")
    args = ap.parse_args(argv)

    suite = GuardrailSuite()
    run_one = _offline_run_one if args.offline else _real_run_one
    result = suite.run(run_one)
    print(f"guardrail: {result.passed}/{result.n} passed"
          + (f"  failures: {', '.join(result.failures)}" if result.failures else ""))

    from app.services.memory.store import MemoryStore

    mem = MemoryStore(args.memory)
    baseline = RegressionBaseline(mem)

    if args.set_baseline:
        baseline.set_baseline(result)
        print(f"baseline recorded ({result.pass_rate:.0%})")
        mem.close()
        return 0

    reg = baseline.certify(result)
    print(f"regression: {'PASS' if reg.passed else 'FAIL'} — {reg.why}")
    if reg.recovered:
        print(f"  recovered: {', '.join(reg.recovered)}")
    mem.close()
    return 0 if reg.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
