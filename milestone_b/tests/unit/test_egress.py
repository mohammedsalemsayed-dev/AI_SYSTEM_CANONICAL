"""Acceptance (Unit): egress broker allowlist enforcement (MILESTONE_C_PLAN.md
section 7). No real network — a fake opener is injected."""

from __future__ import annotations

import pytest

from app.services.egress.broker import EgressBroker, EgressDenied


def _fake_opener(calls: list[str]):
    def opener(url: str, timeout: float) -> bytes:
        calls.append(url)
        return b"payload for " + url.encode()

    return opener


def test_allows_exact_and_subdomain() -> None:
    b = EgressBroker(allowlist=["pypi.org"])
    assert b.allows("https://pypi.org/simple/")
    assert b.allows("https://files.pypi.org/x")
    assert not b.allows("https://pypi.org.evil.com/x")
    assert not b.allows("https://evil.com/x")
    assert not b.allows("not a url")


def test_fetch_denied_records_block_and_never_calls_opener() -> None:
    calls: list[str] = []
    b = EgressBroker(allowlist=["pypi.org"], opener=_fake_opener(calls))
    with pytest.raises(EgressDenied):
        b.fetch("https://evil.com/x")
    assert calls == []
    assert b.blocked == ["https://evil.com/x"]
    assert b.fetched == []


def test_fetch_allowed_returns_tagged_result() -> None:
    calls: list[str] = []
    b = EgressBroker(allowlist=["pypi.org"], opener=_fake_opener(calls))
    result = b.fetch("https://pypi.org/pkg")
    assert result.trust == "retrieved_web"
    assert result.content == b"payload for https://pypi.org/pkg"
    assert calls == ["https://pypi.org/pkg"]
    assert b.fetched == ["https://pypi.org/pkg"]


def test_empty_allowlist_denies_everything() -> None:
    b = EgressBroker(allowlist=[])
    assert not b.allows("https://pypi.org/x")
    with pytest.raises(EgressDenied):
        b.fetch("https://pypi.org/x")
