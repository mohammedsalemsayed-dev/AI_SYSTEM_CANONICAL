"""Provider registry (MILESTONE_G_PLAN.md §2).

The set of routable `(provider, model)` targets with capability + cost priors.
On this machine the local tiers are declared but `available=False` — the local
backend adapter is a named seam, not a cut (DESIGN_TIGHTENING §10). Everything
resolves to a cloud model until that adapter lands, and the router does not need
to change when it does.
"""

from __future__ import annotations

from app.schemas.contracts import ProviderSpec

# The default seed. `agent_sdk` is the subscription path (rate-limited, not
# billed) and stays the default everywhere; `anthropic` is opt-in and billed.
DEFAULT_PROVIDERS: list[ProviderSpec] = [
    ProviderSpec(
        id="agent_sdk", provider="agent_sdk", model="claude-sonnet-5", local=False,
        context_window=200_000, quality_prior=0.82, latency_prior_s=12.0,
        cost_prior_usd=0.0, resource_cost=0.0, privacy_score=0.4, available=True,
        notes="Claude Agent SDK over the CLI subscription; default; no per-token spend",
    ),
    ProviderSpec(
        id="anthropic", provider="anthropic", model="claude-sonnet-5", local=False,
        context_window=200_000, quality_prior=0.85, latency_prior_s=9.0,
        cost_prior_usd=0.03, resource_cost=0.0, privacy_score=0.4, available=False,
        notes="raw Messages API; billed per token; enable explicitly via SLICE_LLM=anthropic",
    ),
    ProviderSpec(
        id="local-small", provider="local", model="", local=True,
        context_window=8_192, quality_prior=0.45, latency_prior_s=3.0,
        cost_prior_usd=0.0, resource_cost=0.35, privacy_score=1.0, available=False,
        notes="seam: small local model for qa_explain / ops",
    ),
    ProviderSpec(
        id="local-coder", provider="local", model="", local=True,
        context_window=16_384, quality_prior=0.6, latency_prior_s=6.0,
        cost_prior_usd=0.0, resource_cost=0.6, privacy_score=1.0, available=False,
        notes="seam: local coding model for code_edit_local / debug",
    ),
    ProviderSpec(
        id="local-reasoner", provider="local", model="", local=True,
        context_window=32_768, quality_prior=0.62, latency_prior_s=10.0,
        cost_prior_usd=0.0, resource_cost=0.7, privacy_score=1.0, available=False,
        notes="seam: local reasoning model for research synthesis / doc_analysis",
    ),
]


class ProviderRegistry:
    def __init__(self, specs: list[ProviderSpec] | None = None) -> None:
        self._by_id: dict[str, ProviderSpec] = {}
        for s in specs if specs is not None else DEFAULT_PROVIDERS:
            self._by_id[s.id] = s.model_copy(deep=True)  # never mutate the caller's / seed list

    def get(self, provider_id: str) -> ProviderSpec | None:
        return self._by_id.get(provider_id)

    def require(self, provider_id: str) -> ProviderSpec:
        s = self._by_id.get(provider_id)
        if s is None:
            raise KeyError(f"unknown provider id {provider_id!r}")
        return s

    def all(self) -> list[ProviderSpec]:
        return list(self._by_id.values())

    def available(self, *, local: bool | None = None, cloud: bool | None = None) -> list[ProviderSpec]:
        out = [s for s in self._by_id.values() if s.available]
        if local is True:
            out = [s for s in out if s.local]
        if cloud is True:
            out = [s for s in out if not s.local]
        return out

    def set_available(self, provider_id: str, value: bool) -> None:
        self.require(provider_id).available = value

    def add(self, spec: ProviderSpec) -> None:
        self._by_id[spec.id] = spec
