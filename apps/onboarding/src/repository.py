"""SQLite persistence for Vendor IQ Pro."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VendorRepository:
    def __init__(self, path: str | Path = "data/vendor_iq.db"):
        self._local = threading.local()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        active = getattr(self._local, 'connection', None)
        if active is not None:
            yield active
            return
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        with self.connect() as connection:
            self._local.connection = connection
            try:
                yield
            finally:
                self._local.connection = None

    def initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS vendors (
                    vendor_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    submitted_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    agent TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    findings_json TEXT NOT NULL,
                    assessed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vendor_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    actor TEXT NOT NULL,
                    note TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_assessment_latest
                    ON assessments(vendor_id, agent, revision);
                CREATE INDEX IF NOT EXISTS ix_audit_vendor
                    ON audit_events(vendor_id, created_at);
            """)

    def replace_portfolio(self, records: list[dict]):
        with self.connect() as db:
            db.execute("DELETE FROM assessments")
            db.execute("DELETE FROM audit_events")
            db.execute("DELETE FROM vendors")
        self.upsert_many(records)

    def upsert_many(self, records: list[dict]):
        now = utc_now()
        with self.connect() as db:
            for record in records:
                vendor_id = str(record["vendor_id"]).strip()
                existing = db.execute(
                    "SELECT revision, status FROM vendors WHERE vendor_id = ?", (vendor_id,)
                ).fetchone()
                revision = (existing["revision"] + 1) if existing else int(record.get("revision_number", 1) or 1)
                status = record.get("lifecycle_status") or (existing["status"] if existing else "Received")
                submitted = record.get("submitted_at") or now
                db.execute("""
                    INSERT INTO vendors(vendor_id, revision, status, source_json, submitted_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vendor_id) DO UPDATE SET
                        revision=excluded.revision, status=excluded.status,
                        source_json=excluded.source_json, updated_at=excluded.updated_at
                """, (vendor_id, revision, status, json.dumps(record, default=str), submitted, now))
                db.execute("""
                    INSERT INTO audit_events(vendor_id,event_type,from_status,to_status,actor,note,payload_json,created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (vendor_id, "Submission accepted" if not existing else "Revision submitted",
                      existing["status"] if existing else None, status, "Vendor Intake Agent",
                      f"Revision {revision} stored", "{}", now))
                approved_at = str(record.get("approved_at", "")).strip()
                if not existing and approved_at and status in {"Handoff Ready", "Created in System (Simulated)"}:
                    db.execute("""
                        INSERT INTO audit_events(vendor_id,event_type,from_status,to_status,actor,note,payload_json,created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (vendor_id, "Vendor approved", "Approval Decision", "Handoff Ready",
                          "Synthetic human approver", "Governed approval evidence supplied with test portfolio.",
                          "{}", approved_at))

    def save_assessments(self, vendor_id: str, revision: int, assessments: list[dict]):
        with self.connect() as db:
            for assessment in assessments:
                db.execute("""
                    INSERT INTO assessments(vendor_id,revision,agent,outcome,severity,findings_json,assessed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (vendor_id, revision, assessment["agent"], assessment["outcome"],
                      assessment["severity"], json.dumps(assessment["findings"]), utc_now()))

    def transition(self, vendor_id: str, to_status: str, actor: str, note: str, event_type: str):
        with self.connect() as db:
            row = db.execute("SELECT status FROM vendors WHERE vendor_id=?", (vendor_id,)).fetchone()
            if not row:
                raise KeyError(vendor_id)
            db.execute("UPDATE vendors SET status=?, updated_at=? WHERE vendor_id=?",
                       (to_status, utc_now(), vendor_id))
            db.execute("""
                INSERT INTO audit_events(vendor_id,event_type,from_status,to_status,actor,note,payload_json,created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (vendor_id, event_type, row["status"], to_status, actor, note, "{}", utc_now()))

    def vendors(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM vendors ORDER BY vendor_id").fetchall()
        return [dict(r) | json.loads(r["source_json"]) for r in rows]

    def latest_assessments(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""
                SELECT a.* FROM assessments a
                JOIN (SELECT vendor_id, agent, MAX(id) id FROM assessments GROUP BY vendor_id, agent) x
                  ON a.id=x.id ORDER BY a.vendor_id, a.agent
            """).fetchall()
        return [dict(r) | {"findings": json.loads(r["findings_json"])} for r in rows]

    def audit(self, vendor_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if vendor_id:
                rows = db.execute("SELECT * FROM audit_events WHERE vendor_id=? ORDER BY created_at DESC", (vendor_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM audit_events ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
