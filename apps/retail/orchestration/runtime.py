"""Durable orchestration ledger around immutable standalone-agent outputs."""

from __future__ import annotations
from orchestration.local_safety import guarded_write

import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from orchestration.contracts import AgentAssessment, REQUIRED_AGENT_IDS, utc_now
from orchestration.executive import orchestrate


TERMINAL_EXECUTION_STATES = {"COMPLETED", "FAILED", "TIMED_OUT", "SKIPPED"}


class OrchestrationLedger:
    """Platform-owned state. It never writes into a standalone agent."""

    def __init__(self, database_path: str | None = None):
        configured = database_path or os.getenv("RETAIL_PLATFORM_DB_PATH")
        self.path = Path(configured or "data/retail_intelligence_platform.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS orchestration_runs (
                    orchestration_run_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    human_gate_status TEXT NOT NULL,
                    assessments_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_executions (
                    orchestration_run_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_run_id TEXT,
                    contract_version TEXT,
                    generated_at TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (orchestration_run_id, agent_id)
                );
                CREATE TABLE IF NOT EXISTS orchestration_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    orchestration_run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT,
                    occurred_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def _fingerprint(assessments: dict[str, AgentAssessment]) -> str:
        evidence = [
            (agent_id, dict(asdict(value), identifiers=sorted(value.identifiers)))
            for agent_id, value in sorted(assessments.items())
            if agent_id in REQUIRED_AGENT_IDS
        ]
        return sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _is_fresh(value: AgentAssessment, now: datetime, max_age_hours: int) -> bool:
        try:
            generated = datetime.fromisoformat(value.generated_at.replace("Z", "+00:00"))
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=timezone.utc)
            return now - timedelta(hours=max_age_hours) <= generated <= now + timedelta(minutes=5)
        except (TypeError, ValueError):
            return False

    @guarded_write
    def synchronize(
        self,
        assessments: dict[str, AgentAssessment],
        *,
        max_age_hours: int = 24,
    ) -> dict:
        """Create or refresh the governed run represented by current evidence."""
        relevant = {key: value for key, value in assessments.items() if key in REQUIRED_AGENT_IDS}
        fingerprint = self._fingerprint(relevant)
        run_id = f"RIP-ORCH-{fingerprint[:16].upper()}"
        now = datetime.now(timezone.utc)
        missing = [agent_id for agent_id in REQUIRED_AGENT_IDS if agent_id not in relevant]
        stale = [
            agent_id for agent_id, value in relevant.items()
            if not self._is_fresh(value, now, max_age_hours)
        ]
        cycles = sorted({value.business_cycle_id for value in relevant.values() if value.business_cycle_id})
        cycle_mismatch = len(cycles) != 1 or any(not value.business_cycle_id for value in relevant.values())
        decision = orchestrate(relevant)
        status = "AWAITING_AGENTS" if missing else "STALE" if stale else "CYCLE_MISMATCH" if cycle_mismatch else "AWAITING_HUMAN_APPROVAL"
        decision_name = decision.decision if not (missing or stale or cycle_mismatch) else "NOT EVALUATED"
        assessment_json = json.dumps({key: asdict(value) for key, value in relevant.items()}, default=list)
        decision_json = json.dumps(asdict(decision), default=list)
        timestamp = now.isoformat()

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT human_gate_status, created_at FROM orchestration_runs WHERE orchestration_run_id = ?",
                (run_id,),
            ).fetchone()
            human_gate = existing["human_gate_status"] if existing else "PENDING" if status == "AWAITING_HUMAN_APPROVAL" else "NOT READY"
            if human_gate == "APPROVED" and status == "AWAITING_HUMAN_APPROVAL":
                status = "COMPLETED"
            elif human_gate == "REJECTED" and status == "AWAITING_HUMAN_APPROVAL":
                status = "REJECTED"
            created_at = existing["created_at"] if existing else timestamp
            connection.execute("""
                INSERT INTO orchestration_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(orchestration_run_id) DO UPDATE SET
                    status=excluded.status, decision=excluded.decision,
                    assessments_json=excluded.assessments_json,
                    decision_json=excluded.decision_json, updated_at=excluded.updated_at
            """, (run_id, fingerprint, status, decision_name, human_gate,
                  assessment_json, decision_json, created_at, timestamp))
            for agent_id in REQUIRED_AGENT_IDS:
                value = relevant.get(agent_id)
                execution_status = "MISSING" if value is None else "STALE" if agent_id in stale else "COMPLETED"
                connection.execute("""
                    INSERT INTO agent_executions VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(orchestration_run_id, agent_id) DO UPDATE SET
                        status=excluded.status, source_run_id=excluded.source_run_id,
                        contract_version=excluded.contract_version,
                        generated_at=excluded.generated_at, error=excluded.error,
                        updated_at=excluded.updated_at
                """, (run_id, agent_id, execution_status,
                      value.source_run_id if value else "",
                      value.contract_version if value else "",
                      value.generated_at if value else "", None, timestamp))
            if not existing:
                connection.execute(
                    "INSERT INTO orchestration_events(orchestration_run_id,event_type,actor,reason,occurred_at) VALUES (?,?,?,?,?)",
                    (run_id, "RUN_CREATED", "SYSTEM", "Agent evidence synchronized", timestamp),
                )

        return self.get(run_id) | {"missing_agents": missing, "stale_agents": stale,
                                   "business_cycle_ids": cycles, "cycle_mismatch": cycle_mismatch}

    @guarded_write
    def decide_human_gate(self, run_id: str, approved: bool, actor: str, reason: str, expected_gate: str | None = None) -> dict:
        if not actor.strip():
            raise ValueError("An approver name is required.")
        if not reason.strip():
            raise ValueError("A decision reason is required.")
        current = self.get(run_id)
        if expected_gate is not None and current["human_gate_status"] != expected_gate:
            raise ValueError("The review changed in another session. Reload before deciding.")
        evidence = current["assessments"]
        refreshed = self.synchronize({key: AgentAssessment(**dict(value, identifiers=set(value['identifiers'])))
                          for key, value in evidence.items()})
        if refreshed["orchestration_run_id"] != run_id:
            raise ValueError("Evidence contract changed; revalidate before deciding this review.")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM orchestration_runs WHERE orchestration_run_id = ?", (run_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"Unknown orchestration run: {run_id}")
            if row["status"] not in {"AWAITING_HUMAN_APPROVAL", "COMPLETED", "REJECTED"}:
                raise ValueError("All three fresh agent outputs are required before a human decision.")
            decision_detail = json.loads(row["decision_json"])
            if approved and decision_detail.get("status") not in {"READY", "WARNING"}:
                raise ValueError("A blocked executive decision cannot be approved; hold the release and remediate it.")
            gate = "APPROVED" if approved else "REJECTED"
            status = "COMPLETED" if approved else "REJECTED"
            now = utc_now()
            connection.execute(
                "UPDATE orchestration_runs SET human_gate_status=?, status=?, updated_at=? WHERE orchestration_run_id=?",
                (gate, status, now, run_id),
            )
            connection.execute(
                "INSERT INTO orchestration_events(orchestration_run_id,event_type,actor,reason,occurred_at) VALUES (?,?,?,?,?)",
                (run_id, f"HUMAN_{gate}", actor.strip(), reason.strip(), now),
            )
        return self.get(run_id)

    def get(self, run_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM orchestration_runs WHERE orchestration_run_id = ?", (run_id,)
            ).fetchone()
            executions = connection.execute(
                "SELECT * FROM agent_executions WHERE orchestration_run_id = ? ORDER BY agent_id", (run_id,)
            ).fetchall()
            events = connection.execute(
                "SELECT * FROM orchestration_events WHERE orchestration_run_id = ? ORDER BY event_id", (run_id,)
            ).fetchall()
        if not row:
            raise KeyError(f"Unknown orchestration run: {run_id}")
        result = dict(row)
        result["assessments"] = json.loads(result.pop("assessments_json"))
        result["decision_detail"] = json.loads(result.pop("decision_json"))
        result["executions"] = [dict(value) for value in executions]
        result["events"] = [dict(value) for value in events]
        return result

    def latest(self) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT orchestration_run_id FROM orchestration_runs ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        return self.get(row["orchestration_run_id"]) if row else None
