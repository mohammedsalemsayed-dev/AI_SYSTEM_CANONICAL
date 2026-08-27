"""Secret isolation (MILESTONE_C_PLAN.md section 2).

Env-backed store: values come from `SLICE_SECRET_<NAME>` variables. Secrets never
enter the sandbox environment — `scrub_env` strips them (by key shape and by exact
value match) from anything handed to a backend. A `secret.use` operation runs
host-side in a broker step, human-approved, with the value injected into that one
call only (broker wiring is left for when a real credential appears).
"""

from __future__ import annotations

import os

_PREFIX = "SLICE_SECRET_"
_SECRETISH_KEY_MARKERS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "APIKEY",
    "API_KEY",
    "CREDENTIAL",
    "PRIVATE_KEY",
    "ACCESS_KEY",
)


class SecretNotFound(KeyError):
    pass


class SecretStore:
    def __init__(
        self, prefix: str = _PREFIX, source: dict[str, str] | None = None
    ) -> None:
        src = source if source is not None else dict(os.environ)
        self._secrets = {
            key[len(prefix) :].lower(): val
            for key, val in src.items()
            if key.startswith(prefix)
        }

    def names(self) -> list[str]:
        return sorted(self._secrets)

    def has(self, name: str) -> bool:
        return name.lower() in self._secrets

    def get(self, name: str) -> str:
        try:
            return self._secrets[name.lower()]
        except KeyError as exc:
            raise SecretNotFound(name) from exc

    def values(self) -> set[str]:
        return {v for v in self._secrets.values() if v}


def _key_looks_secret(key: str) -> bool:
    ku = key.upper()
    return any(marker in ku for marker in _SECRETISH_KEY_MARKERS)


def scrub_env(env: dict[str, str], store: SecretStore) -> dict[str, str]:
    """Return `env` without any entry that looks like a secret by key, or whose
    value exactly matches a stored secret."""
    secret_values = store.values()
    return {
        k: v
        for k, v in env.items()
        if not _key_looks_secret(k) and not (v and v in secret_values)
    }
