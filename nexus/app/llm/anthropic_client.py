"""Real `LLM` provider. Lazy-imports `anthropic` so the package is optional.

Interpreter/Planner are small structured-JSON calls, so the default is
`claude-sonnet-5` (cheaper, adaptive thinking) rather than the `claude-opus-5`
the claude-api skill recommends by default — override with `SLICE_LLM_MODEL`
(e.g. `claude-opus-5`). Auth: the zero-arg `Anthropic()` client resolves
`ANTHROPIC_API_KEY`, then `ANTHROPIC_AUTH_TOKEN`, then an `ant auth login`
profile — run `ant auth status` to see what's active.
"""

from __future__ import annotations

import os
import time

from app.llm.base import LLMResponse

DEFAULT_MODEL = os.environ.get("SLICE_LLM_MODEL", "claude-sonnet-5")


class RefusalError(RuntimeError):
    pass


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 8192) -> None:
        import anthropic  # lazy; only needed for real runs

        self.model = model
        self.max_tokens = max_tokens
        self._client = anthropic.Anthropic()

    def complete(self, *, system: str, prompt: str) -> LLMResponse:
        t0 = time.time()
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        if msg.stop_reason == "refusal":
            raise RefusalError(f"model declined the request ({self.model})")
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        return LLMResponse(
            text=text,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            latency_s=time.time() - t0,
            provider=self.provider,
            model=self.model,
        )
