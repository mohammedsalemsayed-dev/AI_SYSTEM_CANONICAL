"""Real `LLM` provider. Lazy-imports `anthropic` so the package is optional.

Model id comes from `SLICE_LLM_MODEL` (see milestone_b/README.md); the default
here is a placeholder — set the env var to a current id. Consult the `claude-api`
skill for current model ids and the Messages API shape before a real run.
"""

from __future__ import annotations

import os
import time

from app.llm.base import LLMResponse

DEFAULT_MODEL = os.environ.get("SLICE_LLM_MODEL", "claude-sonnet-4-5")


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 4096) -> None:
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
