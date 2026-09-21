"""SQLite persistence for retail validation runs and agent assessments."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from domain.contracts import AgentFinding, RunMetadata


DEFAULT_DB_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "retail_intelligence.db"
)


class AssessmentRepository:
    def __init__(self, database_path: str | Path = DEFAULT_DB_PATH):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS validation_runs (
                    run_id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    validated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    vendor_id TEXT,
                    sku TEXT,
                    po_id TEXT,
                    status TEXT NOT NULL,
                    score REAL NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    validated_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES validation_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_assessment_entity
                    ON assessments(domain, entity_type, entity_id, validated_at);
                CREATE INDEX IF NOT EXISTS idx_assessment_vendor
                    ON assessments(vendor_id, validated_at);
                CREATE INDEX IF NOT EXISTS idx_assessment_sku
                    ON assessments(sku, validated_at);
                CREATE INDEX IF NOT EXISTS idx_assessment_po
                    ON assessments(po_id, validated_at);

                CREATE TABLE IF NOT EXISTS combined_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    po_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES validation_runs(run_id)
                );
                """
            )

    def save_run(self, metadata: RunMetadata) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO validation_runs
                    (run_id, domain, source_file, row_count, validated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    metadata.run_id,
                    metadata.domain,
                    metadata.source_file,
                    metadata.row_count,
                    metadata.validated_at,
                ),
            )

    def save_assessments(
        self,
        metadata: RunMetadata,
        assessments: Iterable[AgentFinding],
        identifiers: Iterable[dict[str, str]],
    ) -> None:
        assessment_list = list(assessments)
        identifier_list = list(identifiers)
        if len(assessment_list) != len(identifier_list):
            raise ValueError("Each assessment requires one identifier mapping.")

        rows = []
        for finding, ids in zip(assessment_list, identifier_list):
            payload = finding.to_dict()
            payload["status"] = finding.status.value
            payload["severity"] = finding.severity.value
            rows.append(
                (
                    metadata.run_id,
                    metadata.domain,
                    finding.agent,
                    finding.entity_type,
                    finding.entity_id,
                    ids.get("vendor_id", ""),
                    ids.get("sku", ""),
                    ids.get("po_id", ""),
                    finding.status.value,
                    finding.score,
                    finding.severity.value,
                    finding.confidence,
                    json.dumps(payload, default=str),
                    metadata.validated_at,
                )
            )

        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO assessments (
                    run_id, domain, agent, entity_type, entity_id,
                    vendor_id, sku, po_id, status, score, severity,
                    confidence, payload_json, validated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def save_decisions(
        self,
        metadata: RunMetadata,
        decisions: Iterable[dict[str, Any]],
    ) -> None:
        rows = [
            (
                metadata.run_id,
                str(decision.get("po_id", "")),
                str(decision.get("recommendation", "NOT_EVALUATED")),
                str(decision.get("reason", "")),
                json.dumps(decision, default=str),
                metadata.validated_at,
            )
            for decision in decisions
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO combined_decisions (
                    run_id, po_id, decision, reason, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def latest_assessment(
        self,
        domain: str,
        entity_type: str,
        entity_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM assessments
                WHERE domain = ? AND entity_type = ? AND entity_id = ?
                ORDER BY validated_at DESC, id DESC
                LIMIT 1
                """,
                (domain, entity_type, entity_id),
            ).fetchone()
        return dict(row) if row else None

    def run_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM validation_runs) AS runs,
                    (SELECT COUNT(*) FROM assessments) AS assessments,
                    (SELECT COUNT(*) FROM combined_decisions) AS decisions
                """
            ).fetchone()
        return dict(row)
