"""Persistent intake contract for connected retail intelligence agents."""

from __future__ import annotations
from orchestration.local_safety import guarded_write

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from orchestration.contracts import AgentAssessment


SUPPORTED_SCHEMAS = {
    "retail-intelligence.catalog.v1",
    "retail-intelligence.vendor.v1",
    "retail-intelligence.po.v1",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_publication(payload: dict[str, Any]) -> None:
    required = {
        "schema", "schema_version", "source", "orchestration_run_id",
        "dataset_run_ids", "policy_version", "executive_decision", "provenance",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"Publication is missing required fields: {', '.join(missing)}")
    if payload["schema"] not in SUPPORTED_SCHEMAS:
        raise ValueError(f"Unsupported publication schema: {payload['schema']}")
    schema_fields = {
        "retail-intelligence.catalog.v1": {"catalog", "item_onboarding", "revenue_impact"},
        "retail-intelligence.vendor.v1": {"vendor_intelligence", "vendor_onboarding", "vendor_health"},
        "retail-intelligence.po.v1": {"po_intelligence", "po_health", "financial_impact"},
    }[payload["schema"]]
    missing_schema_fields = sorted(schema_fields - payload.keys())
    if missing_schema_fields:
        raise ValueError(f"Publication is missing schema fields: {', '.join(missing_schema_fields)}")
    if payload.get("synchronization_status") != "VERIFIED":
        raise ValueError("Only synchronized agent outputs can enter executive orchestration.")
    if not payload.get("dataset_run_ids"):
        raise ValueError("At least one dataset run ID is required.")
    if not payload.get("business_cycle_id"):
        raise ValueError("business_cycle_id is required for cross-agent orchestration.")


def evidence_timestamp(publication):
    payload = publication['payload']
    return (payload.get('generated_at') or payload.get('provenance', {}).get('validated_at')
            or payload.get('published_at') or publication['received_at'])


class PublicationStore:
    def __init__(self, database_path: str | None = None):
        configured = database_path or os.getenv("RETAIL_PLATFORM_DB_PATH")
        self.path = Path(configured or "data/retail_intelligence_platform.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS agent_publications (
                    publication_id TEXT PRIMARY KEY,
                    orchestration_run_id TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    schema_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    acknowledgement_json TEXT NOT NULL,
                    received_at TEXT NOT NULL
                )
            """)

    @guarded_write
    def receive(self, publication_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        validate_publication(payload)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT acknowledgement_json, payload_json FROM agent_publications WHERE publication_id = ? OR orchestration_run_id = ?",
                (publication_id, payload["orchestration_run_id"]),
            ).fetchone()
            if existing:
                if json.loads(existing['payload_json']) != payload:
                    raise ValueError("Publication identity already exists with different evidence.")
                return json.loads(existing["acknowledgement_json"])
            acknowledgement = {
                "acknowledgement_id": f"RIP-ACK-{publication_id.removeprefix('PUB-')}",
                "publication_id": publication_id, "accepted": True, "status": "ACCEPTED",
                "source": payload["source"], "orchestration_run_id": payload["orchestration_run_id"],
                "received_at": utc_now(),
            }
            connection.execute(
                "INSERT INTO agent_publications VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (publication_id, payload["orchestration_run_id"], payload["source"], payload["schema"],
                 "ACCEPTED", json.dumps(payload), json.dumps(acknowledgement), acknowledgement["received_at"]),
            )
            return acknowledgement

    def get(self, publication_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_publications WHERE publication_id = ?", (publication_id,)
            ).fetchone()
        return self._row(row) if row else None

    def latest(self, source: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_publications WHERE source = ? ORDER BY received_at DESC LIMIT 1", (source,)
            ).fetchone()
        return self._row(row) if row else None

    def list_publications(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM agent_publications ORDER BY received_at DESC").fetchall()
        return [self._row(row) for row in rows]

    def health_summary(self, max_age_hours: int = 24) -> dict[str, Any]:
        """Return integration readiness, not merely receiver liveness."""
        now = datetime.now(timezone.utc)
        publications = {source: self.latest(source) for source in (
            "VENDOR_IQ_PRO", "CATALOG_IQ_PRO", "PO_INTELLIGENCE",
        )}

        def evidence(source: str) -> dict[str, Any]:
            publication = publications[source]
            if not publication:
                return {"status": "MISSING", "source": source, "publication_id": None,
                        "source_run_id": None, "received_at": None, "age_hours": None}
            received = datetime.fromisoformat(evidence_timestamp(publication).replace("Z", "+00:00"))
            if received.tzinfo is None:
                received = received.replace(tzinfo=timezone.utc)
            age = max(0.0, (now - received).total_seconds() / 3600)
            return {
                "status": "CURRENT" if received >= now - timedelta(hours=max_age_hours) else "STALE",
                "source": source,
                "publication_id": publication["publication_id"],
                "source_run_id": publication["orchestration_run_id"],
                "received_at": publication["received_at"],
                "age_hours": round(age, 1),
            }

        vendor = evidence("VENDOR_IQ_PRO")
        catalog = evidence("CATALOG_IQ_PRO")
        po = evidence("PO_INTELLIGENCE")
        onboarding_sources = [vendor, catalog]
        onboarding_status = (
            "MISSING" if any(value["status"] == "MISSING" for value in onboarding_sources)
            else "STALE" if any(value["status"] == "STALE" for value in onboarding_sources)
            else "CURRENT"
        )
        domains = {
            "onboarding_intelligence": {"status": onboarding_status, "sources": onboarding_sources},
            "catalog_iq": {"status": catalog["status"], "sources": [catalog]},
            "po_intelligence": {"status": po["status"], "sources": [po]},
        }
        ready = all(value["status"] == "CURRENT" for value in domains.values())
        return {
            "status": "healthy" if ready else "degraded",
            "service": "retail-intelligence-intake",
            "receiver": "UP",
            "integration_ready": ready,
            "freshness_threshold_hours": max_age_hours,
            "checked_at": now.isoformat(),
            "domains": domains,
        }

    @staticmethod
    def _row(row) -> dict[str, Any]:
        return {
            "publication_id": row["publication_id"], "orchestration_run_id": row["orchestration_run_id"],
            "source": row["source"], "schema": row["schema_name"], "status": row["status"],
            "payload": json.loads(row["payload_json"]),
            "acknowledgement": json.loads(row["acknowledgement_json"]), "received_at": row["received_at"],
        }


def catalog_publication_to_assessment(publication: dict[str, Any]) -> AgentAssessment:
    payload = publication["payload"]
    catalog = payload["catalog"]
    revenue = payload["revenue_impact"]
    rows = payload.get("sku_health") or []
    findings = [{
        "Identifier": row.get("sku", "Unidentified product"), "Score": row.get("readiness", 0),
        "Status": "BLOCKED" if row.get("severity") == "CRITICAL" else "WARNING" if row.get("severity") == "WARNING" else "READY",
        "Issue": ", ".join(row.get("affected_fields") or []) or "No material catalog-quality gaps",
        "Action": "Correct catalog defects" if row.get("severity") != "NONE" else "Catalog record is publication-ready",
    } for row in rows]
    return AgentAssessment(
        agent_id="catalog_iq", label="Catalog IQ Pro", score=float(catalog.get("health_score") or 0),
        status="BLOCKED" if catalog.get("critical_skus") else "WARNING" if catalog.get("warning_skus") else "READY",
        total_records=int(catalog.get("total_skus") or 0), ready_records=int(catalog.get("clean_skus") or 0),
        warning_records=int(catalog.get("warning_skus") or 0), blocked_records=int(catalog.get("critical_skus") or 0),
        financial_exposure=float(revenue.get("revenue_at_risk") or 0), findings=findings,
        identifiers={str(row.get("sku")).strip().upper() for row in rows if row.get("sku")},
        source_file=f"Connected package {publication['publication_id']}",
        source_run_id=publication["orchestration_run_id"],
        generated_at=evidence_timestamp(publication),
        business_cycle_id=payload.get("business_cycle_id") or "",
    )


def vendor_publication_to_assessment(publication: dict[str, Any]) -> AgentAssessment:
    payload = publication["payload"]
    summary = payload["vendor_intelligence"]
    rows = payload.get("vendor_health") or []
    findings = [{
        "Identifier": row.get("vendor_id", "Unidentified vendor"),
        "Score": row.get("score", 0),
        "Status": "BLOCKED" if row.get("severity") == "CRITICAL" else "WARNING" if row.get("severity") == "WARNING" else "READY",
        "Issue": ", ".join(row.get("issues") or []) or "No material vendor-governance gaps",
        "Action": "Resolve vendor onboarding or risk findings" if row.get("severity") != "NONE" else "Vendor is governance-ready",
    } for row in rows]
    return AgentAssessment(
        agent_id="vendor_intelligence", label="Vendor Intelligence", score=float(summary.get("health_score") or 0),
        status="BLOCKED" if summary.get("critical_vendors") else "WARNING" if summary.get("warning_vendors") else "READY",
        total_records=int(summary.get("total_vendors") or 0), ready_records=int(summary.get("ready_vendors") or 0),
        warning_records=int(summary.get("warning_vendors") or 0), blocked_records=int(summary.get("critical_vendors") or 0),
        financial_exposure=float(summary.get("business_value_at_risk") or 0), findings=findings,
        identifiers={str(row.get("vendor_id")).strip().upper() for row in rows if row.get("vendor_id")},
        source_file=f"Connected package {publication['publication_id']}",
        source_run_id=publication["orchestration_run_id"],
        generated_at=evidence_timestamp(publication),
        business_cycle_id=payload.get("business_cycle_id") or "",
    )


def onboarding_publications_to_assessment(
    vendor_publication: dict[str, Any], catalog_publication: dict[str, Any]
) -> AgentAssessment:
    """Combine independently governed vendor and item onboarding outputs."""
    vendor_payload = vendor_publication["payload"]
    catalog_payload = catalog_publication["payload"]
    vendor_cycle = vendor_payload.get("business_cycle_id", "")
    catalog_cycle = catalog_payload.get("business_cycle_id", "")
    if not vendor_cycle or vendor_cycle != catalog_cycle:
        raise ValueError("Vendor and item onboarding outputs belong to different business cycles.")
    vendor = vendor_payload["vendor_onboarding"]
    item = catalog_payload["item_onboarding"]
    vendor_total = int(vendor.get("submitted_vendors") or 0)
    item_total = int(item.get("submitted_items") or 0)
    vendor_score = float(vendor.get("readiness_score") or 0)
    item_score = float(item.get("readiness_score") or 0)
    score = vendor_score * 0.40 + item_score * 0.60
    vendor_blocked = int(vendor.get("critical_vendors") or vendor.get("correction_required") or 0)
    item_blocked = int(item.get("correction_required") or 0)
    vendor_warning = int(vendor.get("warning_vendors") or 0)
    item_warning = int(item.get("warning_items") or 0)
    status = "BLOCKED" if vendor_blocked or item_blocked else "WARNING" if vendor_warning or item_warning else "READY"
    ready = vendor_total + item_total - vendor_blocked - item_blocked - vendor_warning - item_warning
    findings = []
    for row in vendor_publication["payload"].get("vendor_health") or []:
        if row.get("severity") != "NONE":
            findings.append({"Record type": "Vendor", "Identifier": row.get("vendor_id"),
                             "Status": row.get("severity"), "Issue": ", ".join(row.get("issues") or []),
                             "Accountable team": "Vendor Operations", "Workflow status": "Open",
                             "Priority": "P1" if row.get("severity") == "CRITICAL" else "P2",
                             "Action": "Resolve vendor onboarding findings and revalidate"})
    for row in catalog_publication["payload"].get("sku_health") or []:
        if row.get("severity") != "NONE":
            findings.append({"Record type": "Item", "Identifier": row.get("sku"),
                             "Status": row.get("severity"), "Issue": ", ".join(row.get("affected_fields") or []),
                             "Accountable team": "Catalog Operations", "Workflow status": "Open",
                             "Priority": "P1" if row.get("severity") == "CRITICAL" else "P2",
                             "Action": "Correct item information and revalidate"})
    identifiers = {
        f"VENDOR:{str(row.get('vendor_id')).strip().upper()}"
        for row in vendor_publication["payload"].get("vendor_health") or [] if row.get("vendor_id")
    } | {
        f"ITEM:{str(row.get('sku')).strip().upper()}"
        for row in catalog_publication["payload"].get("sku_health") or [] if row.get("sku")
    }
    return AgentAssessment(
        agent_id="onboarding_intelligence", label="Onboarding Intelligence", score=round(score, 1),
        status=status, total_records=vendor_total + item_total, ready_records=ready,
        warning_records=vendor_warning + item_warning, blocked_records=vendor_blocked + item_blocked,
        financial_exposure=float(vendor_publication["payload"]["vendor_intelligence"].get("business_value_at_risk") or 0),
        findings=findings, identifiers=identifiers,
        source_file=f"Vendor {vendor_publication['publication_id']} + Catalog {catalog_publication['publication_id']}",
        source_run_id=(
            f"{vendor_publication['orchestration_run_id']}+"
            f"{catalog_publication['orchestration_run_id']}"
        ),
        generated_at=min(evidence_timestamp(vendor_publication), evidence_timestamp(catalog_publication)),
        business_cycle_id=vendor_cycle,
    )


def po_publication_to_assessment(publication: dict[str, Any]) -> AgentAssessment:
    """Normalize an acknowledged standalone PO package for orchestration."""
    payload = publication["payload"]
    summary = payload["po_intelligence"]
    rows = payload.get("po_health") or []
    findings = [{
        "Identifier": row.get("sku") or row.get("po_id") or "Unidentified PO line",
        "PO": row.get("po_id"),
        "Vendor": row.get("vendor_id"),
        "Score": row.get("readiness", 0),
        "Status": "BLOCKED" if row.get("severity") == "CRITICAL" else "WARNING" if row.get("severity") == "WARNING" else "READY",
        "Issue": "; ".join(row.get("issues") or []) or "No PO validation gaps",
        "Action": "Correct PO fields before release" if row.get("severity") == "CRITICAL" else "Review PO warning" if row.get("severity") == "WARNING" else "PO line is release-ready",
    } for row in rows]
    return AgentAssessment(
        agent_id="po_intelligence",
        label="PO / Buying Intelligence",
        release_blockers=(payload.get("cycle_evidence", {}).get("reconciliation_issues", []) +
                          (["Reconciled commercial evidence is required in the Decision workspace."]
                           if payload.get("cycle_evidence", {}).get("financial", {}).get("coverage_pct") != 100 else [])),
        score=float(summary.get("readiness_score") or 0),
        status="BLOCKED" if summary.get("blocked_lines") else "WARNING" if summary.get("warning_lines") else "READY",
        total_records=int(summary.get("total_lines") or 0),
        ready_records=int(summary.get("ready_lines") or 0),
        warning_records=int(summary.get("warning_lines") or 0),
        blocked_records=int(summary.get("blocked_lines") or 0),
        financial_exposure=float(summary.get("financial_exposure") or 0),
        findings=findings,
        identifiers={str(row.get("sku")).strip().upper() for row in rows if row.get("sku")},
        source_file=f"Connected package {publication['publication_id']}",
        source_run_id=publication["orchestration_run_id"],
        generated_at=evidence_timestamp(publication),
        business_cycle_id=payload.get("business_cycle_id") or "",
    )
