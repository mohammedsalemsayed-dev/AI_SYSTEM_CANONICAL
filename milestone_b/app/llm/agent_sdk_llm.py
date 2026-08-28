"""`LLM` provider that runs a single-turn Claude Agent SDK query.

Uses the same auth path as Claude Code (the `claude` CLI's OAuth session), so it
works on a Claude Pro / Max subscription with no API key and no per-token spend
(subject to the subscription's rate limits). Lazy-imports `claude_agent_sdk`.

This is a degenerate use of the agent loop — no tools, one turn — purely to get
the Interpreter / Planner JSON. For the Builder, `AgentSDKBuilder` already uses
the SDK directly.
"""

from __future__ import annotations

import asyncio
import time

from app.llm.base import LLMResponse


class AgentSDKLLM:
    provider = "agent_sdk"

    def __init__(self, model: str | None = None) -> None:
        # None -> whatever the CLI/subscription defaults to
        self.model = model or "subscription-default"

    def complete(self, *, system: str, prompt: str) -> LLMResponse:
        t0 = time.time()
        text, (inp, out) = asyncio.run(self._run(system, prompt))
        return LLMResponse(
            text=text,
            input_tokens=inp,
            output_tokens=out,
            latency_s=time.time() - t0,
            provider=self.provider,
            model=self.model,
        )

    async def _run(self, system: str, prompt: str) -> tuple[str, tuple[int, int]]:
        from claude_agent_sdk import (  # lazy
            AssistantMessage,
            ClaudeAgentOptions,
            ResultError,
            ResultMessage,
            TextBlock,
            query,
        )

        opts_kw: dict = {
            # no tools, so the model can't loop; keep headroom for a
            # thinking turn + the answer turn.
            "max_turns": 8,
            "allowed_tools": [],
            "permission_mode": "default",
        }
        if self.model and self.model != "subscription-default":
            opts_kw["model"] = self.model
        options = ClaudeAgentOptions(**opts_kw)

        full_prompt = f"{system}\n\n{prompt}"
        chunks: list[str] = []
        final: str | None = None
        inp = out = 0
        try:
            async for message in query(prompt=full_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            chunks.append(block.text)
                elif isinstance(message, ResultMessage):
                    final = getattr(message, "result", None)
                    usage = getattr(message, "usage", None)
                    if usage is not None:
                        # SDK >= 0.2: `usage` is a dict; older builds exposed an
                        # object. With prompt caching the input is split across
                        # `input_tokens` + `cache_read_input_tokens` +
                        # `cache_creation_input_tokens` — sum them for a true count.
                        u = usage if isinstance(usage, dict) else {
                            k: getattr(usage, k, 0)
                            for k in ("input_tokens", "output_tokens",
                                      "cache_read_input_tokens",
                                      "cache_creation_input_tokens")
                        }
                        inp = sum(
                            int(u.get(k, 0) or 0)
                            for k in ("input_tokens", "cache_read_input_tokens",
                                      "cache_creation_input_tokens")
                        )
                        out = int(u.get("output_tokens", 0) or 0)
        except ResultError:
            # e.g. max-turns hit; fall through and use whatever text we collected
            if not chunks:
                raise

        text = "".join(chunks) or (final or "")
        if not text:
            raise RuntimeError("Agent SDK returned no text (check `claude` CLI auth)")
        return text, (inp, out)
