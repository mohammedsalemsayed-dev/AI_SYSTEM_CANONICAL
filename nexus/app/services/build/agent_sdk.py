"""`Builder` that drives the Claude Agent SDK headless inside a workspace copy.

Lazy-imports `claude_agent_sdk` so the package is optional. This adapter is NOT
exercised by the slice test suite (that runs on `ScriptedBuilder`); it is the
Choice-B executor for the Day 10 real-task run. Verify the call shape against the
installed SDK version before relying on it — the SDK API may have drifted.
"""

from __future__ import annotations

import asyncio
import os

from app.schemas.contracts import PlanStep, TaskContract
from app.services.build.base import BuildOutput
from app.services.build.workspace_copy import diff_workspace
from app.services.verify.verifier_t0 import extract_pytest_target

_PROMPT = """You are the Builder in an autonomous coding system. Work only inside this directory.

OBJECTIVE:
{objective}

THIS STEP:
{intent}

VERIFICATION TARGET:
{target}
{constraints}

Process:
1. First READ the verification target test file. Note exactly what it asserts —
   return values, exact exception types AND exact message strings/regexes,
   boundary values, edge cases.
2. Make the smallest source change that makes that test pass *as written*. Match
   its exact expectations — do not invent a different error message or a
   near-equivalent behaviour.
3. Do not edit the test. Do not run the test suite yourself — a separate stage
   verifies. When done, stop.
"""


class AgentSDKBuilder:
    name = "agent_sdk"

    def __init__(self, model: str | None = None, max_turns: int = 40) -> None:
        self.model = model
        self.max_turns = max_turns

    def execute(
        self, *, task_id: str, step: PlanStep, contract: TaskContract, workspace: str
    ) -> BuildOutput:
        # the SDK's `cwd=` option does NOT set the agent's actual working
        # directory (observed on claude_agent_sdk 0.2.145: the agent writes to a
        # stale baked-in path and nothing lands in `workspace`). Chdir the
        # process for the duration of the call — restore it no matter what.
        prev_cwd = os.getcwd()
        try:
            os.chdir(workspace)
        except OSError as exc:
            return BuildOutput(exit_code=1, error=f"agent sdk: bad workspace {workspace}: {exc!r}")
        try:
            transcript = asyncio.run(self._run(step, contract, workspace))
        except Exception as exc:
            return BuildOutput(exit_code=1, error=f"agent sdk error: {exc!r}")
        finally:
            try:
                os.chdir(prev_cwd)
            except OSError:
                pass

        diff, names = diff_workspace(workspace)
        if not diff.strip():
            return BuildOutput(
                changed_paths=[],
                diff="",
                stdout=transcript[-4000:],
                exit_code=1,
                error="builder produced no change",
            )
        return BuildOutput(
            changed_paths=names, diff=diff, stdout=transcript[-4000:], exit_code=0
        )

    async def _run(
        self, step: PlanStep, contract: TaskContract, workspace: str
    ) -> str:
        from claude_agent_sdk import ClaudeAgentOptions, query  # lazy

        opt_kw = dict(
            cwd=workspace,
            add_dirs=[workspace],                      # grant write access to the copy
            permission_mode="bypassPermissions",       # headless: no interactive approval
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            max_turns=self.max_turns,
        )
        if self.model:
            opt_kw["model"] = self.model
        # load the user's real config (auth, model, MCP) when the SDK supports it
        try:
            options = ClaudeAgentOptions(
                setting_sources=["user", "project", "local"], **opt_kw
            )
        except TypeError:
            options = ClaudeAgentOptions(**opt_kw)  # older SDK without setting_sources
        target = extract_pytest_target(contract.required_evidence) or "(not specified)"
        constraints = (
            "\nCONSTRAINTS (address every one):\n"
            + "\n".join(f"- {c}" for c in contract.constraints)
            if contract.constraints
            else ""
        )
        prompt = _PROMPT.format(
            objective=contract.objective,
            intent=step.intent,
            target=target,
            constraints=constraints,
        )
        chunks: list[str] = []
        async for message in query(prompt=prompt, options=options):
            text = getattr(message, "text", None) or getattr(message, "result", None)
            if not text:
                # AssistantMessage carries a list of content blocks, not `.text`
                for blk in getattr(message, "content", None) or []:
                    bt = getattr(blk, "text", None)
                    if bt:
                        chunks.append(str(bt))
            if text:
                chunks.append(str(text))
        return "\n".join(chunks)
