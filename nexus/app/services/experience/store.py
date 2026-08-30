"""ExperienceStore (MILESTONE_F_PLAN.md §2). SQLite-backed; one row per
ExperienceRecord. Capture on a verified completion; retrieve advisory matches at
planning; advance through the lifecycle; quarantine on a catastrophic outcome.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from app.schemas.contracts import ExperienceRecord
from app.services.experience.lifecycle import (
    can_transition,
    gate_candidate_to_validated,
    gate_observed_to_candidate,
    should_go_stale,
    should_quarantine,
)
from app.services.experience.signature import signatures_match

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experience (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    id        TEXT NOT NULL UNIQUE,
    signature TEXT NOT NULL,
    strategy  TEXT NOT NULL,
    state     TEXT NOT NULL,
    payload   TEXT NOT NULL,
    ts        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_exp_state ON experience (state);
"""


class ExperienceStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- capture ---------------------------------------------------- #
    def capture(
        self,
        *,
        signature: str,
        strategy: str,
        actions: list[str],
        evidence_refs: list[str],
        success_score: float,
        verify_tier: str,
    ) -> ExperienceRecord | None:
        is_new = not self._exists(signature, strategy)
        exp = ExperienceRecord(
            signature=signature, strategy=strategy, actions=actions,
            evidence_refs=evidence_refs, success_score=success_score,
            validation_state="OBSERVED", outcome=f"verified@{verify_tier}",
        )
        ok, why = gate_observed_to_candidate(
            verify_tier=verify_tier, is_new_signature_strategy=is_new
        )
        if ok:
            exp.validation_state = "CANDIDATE"
            exp.promotion_history.append(f"OBSERVED->CANDIDATE: {why}")
        self._insert(exp)
        return exp

    # -- retrieve ------------------------------------------------- #
    def retrieve(
        self, signature: str, *, states: tuple[str, ...] = ("PROMOTED", "MONITORED")
    ) -> list[ExperienceRecord]:
        out = []
        for exp in self._by_states(states):
            if exp.validation_state == "QUARANTINED":
                continue
            if signatures_match(exp.signature, signature):
                out.append(exp)
        return out

    # -- lifecycle ---------------------------------------------- #
    def advance(self, exp_id: str, target: str, *, note: str = "") -> ExperienceRecord:
        exp = self.get(exp_id)
        if exp is None:
            raise KeyError(exp_id)
        if not can_transition(exp.validation_state, target):
            raise ValueError(f"{exp.validation_state} -> {target} not allowed")
        exp.promotion_history.append(f"{exp.validation_state}->{target}: {note}")
        exp.validation_state = target
        self._update(exp)
        return exp

    def record_use(self, exp_id: str, *, verified: bool, catastrophic: bool = False) -> ExperienceRecord:
        exp = self.get(exp_id)
        if exp is None:
            raise KeyError(exp_id)
        m = exp.monitoring_metrics
        n = int(m.get("trailing_n", 0)) + 1
        succ = m.get("trailing_success", 1.0)
        m["trailing_n"] = min(n, 20)
        m["trailing_success"] = (succ * (n - 1) + (1.0 if verified else 0.0)) / n
        self._update(exp)
        q, why = should_quarantine(exp, catastrophic=catastrophic)
        if q and exp.validation_state != "QUARANTINED":
            return self.advance(exp_id, "QUARANTINED", note=why)
        s, swhy = should_go_stale(exp)
        if s and exp.validation_state in ("PROMOTED", "MONITORED"):
            return self.advance(exp_id, "STALE", note=swhy)
        return exp

    def add_shadow_result(
        self, exp_id: str, *, verified: bool, cost_ratio: float = 1.0, week: int | None = None
    ) -> ExperienceRecord:
        exp = self.get(exp_id)
        if exp is None:
            raise KeyError(exp_id)
        exp.shadow_replay_log.append(
            {"verified": verified, "cost_ratio": cost_ratio,
             "week": week if week is not None else int(time.time() // (7 * 86400))}
        )
        self._update(exp)
        return exp

    def try_validate(self, exp_id: str) -> tuple[ExperienceRecord, bool, str]:
        """CANDIDATE -> VALIDATED if the shadow-replay gate passes."""
        exp = self.get(exp_id)
        if exp is None:
            raise KeyError(exp_id)
        ok, why = gate_candidate_to_validated(exp)
        if ok and exp.validation_state == "CANDIDATE":
            return self.advance(exp_id, "VALIDATED", note=why), True, why
        return exp, False, why

    def try_promote(
        self, exp_id: str, *, human_approved: bool = False, report=None
    ) -> tuple[ExperienceRecord, "object"]:
        """VALIDATED -> PROMOTED -> (auto) MONITORED.

        With `report` (a Milestone I `EvalReport` from a real held-out replay +
        guardrail gate) the decision is that report. Without one, the
        `experience/eval.py` stub is used so the state machine is always
        exercised offline. Returns (record, decision)."""
        exp = self.get(exp_id)
        if exp is None:
            raise KeyError(exp_id)

        if report is not None:
            ok = report.decision == "promote"
            why = report.why
            if report.guardrail is not None:
                exp.guardrail_result = abs(report.guardrail.drop_pp)
            exp.monitoring_metrics["heldout_n"] = report.heldout_n
            self._update(exp)
            decision = report
        else:
            from app.services.experience.eval import promote_decision

            decision = promote_decision(exp, human_approved=human_approved)
            ok = decision.ok
            why = decision.why
            self._update(exp)  # persist heldout_n / guardrail_result folded in by the eval

        if ok and exp.validation_state == "VALIDATED":
            exp = self.advance(exp_id, "PROMOTED", note=why)
            exp = self.advance(exp_id, "MONITORED", note="auto after PROMOTED")
        return exp, decision

    def sweep_stale(self) -> list[ExperienceRecord]:
        """Move every MONITORED/PROMOTED experience that meets a §8 stale
        condition to STALE. Returns the ones moved."""
        moved = []
        for exp in self._by_states(("PROMOTED", "MONITORED")):
            s, why = should_go_stale(exp)
            if s:
                moved.append(self.advance(exp.id, "STALE", note=why))
        return moved

    # -- helpers ---------------------------------------------- #
    def get(self, exp_id: str) -> ExperienceRecord | None:
        row = self._conn.execute(
            "SELECT payload FROM experience WHERE id=?", (exp_id,)
        ).fetchone()
        return ExperienceRecord.model_validate_json(row[0]) if row else None

    def all(self) -> list[ExperienceRecord]:
        return [
            ExperienceRecord.model_validate_json(r[0])
            for r in self._conn.execute("SELECT payload FROM experience ORDER BY seq")
        ]

    def _by_states(self, states: tuple[str, ...]) -> list[ExperienceRecord]:
        marks = ",".join("?" * len(states))
        rows = self._conn.execute(
            f"SELECT payload FROM experience WHERE state IN ({marks}) ORDER BY seq", states
        ).fetchall()
        return [ExperienceRecord.model_validate_json(r[0]) for r in rows]

    def _exists(self, signature: str, strategy: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM experience WHERE signature=? AND strategy=? LIMIT 1",
                (signature, strategy),
            ).fetchone()
            is not None
        )

    def _insert(self, exp: ExperienceRecord) -> None:
        self._conn.execute(
            "INSERT INTO experience (id, signature, strategy, state, payload, ts) VALUES (?,?,?,?,?,?)",
            (exp.id, exp.signature, exp.strategy, exp.validation_state,
             exp.model_dump_json(), exp.ts),
        )
        self._conn.commit()

    def _update(self, exp: ExperienceRecord) -> None:
        self._conn.execute(
            "UPDATE experience SET state=?, payload=? WHERE id=?",
            (exp.validation_state, exp.model_dump_json(), exp.id),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
