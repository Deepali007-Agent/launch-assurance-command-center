"""Authenticated Vendor IQ publication contract for Retail Intelligence Platform."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import uuid

import pandas as pd


OUTBOX = Path("data/vendor_publication_outbox.json")


def _records(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    clean = frame.copy()
    clean = clean.where(pd.notna(clean), None)
    return clean.to_dict("records")


def build_publication(vendors: pd.DataFrame, assessments: pd.DataFrame, kpis: dict) -> dict:
    rows = _records(vendors)
    latest = _records(assessments)
    critical_ids = {
        str(row.get("vendor_id")) for row in latest if str(row.get("severity", "")).lower() == "critical"
    }
    warning_ids = {
        str(row.get("vendor_id")) for row in latest if str(row.get("severity", "")).lower() == "warning"
    } - critical_ids
    identifiers = sorted({str(row.get("vendor_id")) for row in rows if row.get("vendor_id")})
    ready = max(len(identifiers) - len(critical_ids) - len(warning_ids), 0)
    score = round(100 * (ready + 0.5 * len(warning_ids)) / len(identifiers), 1) if identifiers else 0.0
    exposure_result = kpis.get("opportunity_at_risk")
    exposure = float(getattr(exposure_result, "value", 0) or 0)
    snapshot = json.dumps(
        {"vendors": rows, "assessments": latest,
         "cycle": os.getenv("RETAIL_BUSINESS_CYCLE_ID", "").strip()},
        sort_keys=True, default=str,
    )
    digest = hashlib.sha256(snapshot.encode()).hexdigest()[:16].upper()
    vendor_health = []
    by_vendor: dict[str, list[dict]] = {}
    for finding in latest:
        by_vendor.setdefault(str(finding.get("vendor_id")), []).append(finding)
    for row in rows:
        vendor_id = str(row.get("vendor_id"))
        related = by_vendor.get(vendor_id, [])
        severity = "CRITICAL" if vendor_id in critical_ids else "WARNING" if vendor_id in warning_ids else "NONE"
        vendor_health.append({
            "vendor_id": vendor_id,
            "vendor": row.get("legal_name") or row.get("trading_name") or vendor_id,
            "status": row.get("status", "Received"),
            "severity": severity,
            "score": 0 if severity == "CRITICAL" else 60 if severity == "WARNING" else 100,
            "issues": sorted({f"{finding.get('field', '')}: {finding.get('issue', '')}" for item in related for finding in item.get("findings", [])}),
            "owners": sorted({str(finding.get('owner', 'Vendor Operations')) for item in related for finding in item.get("findings", [])}),
            "required_evidence": sorted({str(finding.get('how_to_fix', 'Correct and revalidate')) for item in related for finding in item.get("findings", [])}),
        })
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "Received")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "schema": "retail-intelligence.vendor.v1",
        "evaluator_type": "deterministic",
        "input_contract_version": "retail-source-input-1.0",
        "evidence_contract_version": "retail-cycle-controls-2.0",
        "schema_version": "1.1",
        "source": "VENDOR_IQ_PRO",
        "business_cycle_id": os.getenv("RETAIL_BUSINESS_CYCLE_ID", "").strip(),
        "orchestration_run_id": f"VENDOR-ORCH-{digest}-ONB1",
        "dataset_run_ids": [f"VENDOR-DATA-{digest}"],
        "policy_version": "vendor-governance-policy-1.0",
        "synchronization_status": "VERIFIED",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "executive_decision": {
            "decision": "HOLD" if critical_ids else "CONDITIONAL" if warning_ids else "READY",
            "reason": f"{len(critical_ids)} vendors have critical blockers.",
        },
        "vendor_intelligence": {
            "total_vendors": len(identifiers), "ready_vendors": ready,
            "warning_vendors": len(warning_ids), "critical_vendors": len(critical_ids),
            "health_score": score, "business_value_at_risk": exposure, "currency": "INR",
        },
        "vendor_onboarding": {
            "submitted_vendors": len(identifiers),
            "validation_cleared": ready + len(warning_ids),
            "approval_ready": status_counts.get("Approval Decision", 0),
            "correction_required": status_counts.get("Correction Required", 0),
            "on_hold": status_counts.get("On Hold", 0),
            "handoff_ready": status_counts.get("Handoff Ready", 0),
            "created": status_counts.get("Created in System (Simulated)", 0),
            "critical_vendors": len(critical_ids),
            "warning_vendors": len(warning_ids),
            "readiness_score": score,
            "decision": "BLOCKED" if critical_ids else "CONDITIONAL" if warning_ids else "READY",
            "calculation_note": "Unique latest vendor records; each vendor is counted once regardless of the number of findings.",
        },
        "vendor_health": vendor_health,
        "provenance": {"source_agents": sorted({str(row.get("agent")) for row in latest if row.get("agent")})},
    }


def publish(payload: dict) -> dict:
    endpoint = os.getenv("RETAIL_INTELLIGENCE_API_URL", "").strip()
    token = os.getenv("RETAIL_INTELLIGENCE_API_TOKEN", "").strip()
    if not endpoint or not token:
        raise RuntimeError("Retail Intelligence publishing destination is not configured.")
    publication_id = f"PUB-{uuid.uuid4().hex[:16].upper()}"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, default=str).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Idempotency-Key": publication_id, "X-VendorIQ-Schema": payload["schema"]},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            acknowledgement = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Parent platform rejected publication ({exc.code}): {exc.read().decode()}") from exc
    if acknowledgement.get("accepted") is not True or acknowledgement.get("orchestration_run_id") != payload.get("orchestration_run_id"):
        raise RuntimeError("Retail Intelligence did not confirm acceptance of this assessment.")
    state = {"publication_id": acknowledgement.get("publication_id", publication_id), "status": "Published", "payload": payload,
             "acknowledgement": acknowledgement, "updated_at": datetime.now(timezone.utc).isoformat()}
    OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    OUTBOX.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    return state


def publication_state(payload: dict) -> dict:
    if not OUTBOX.exists():
        return {"status": "Ready to publish"}
    try:
        state = json.loads(OUTBOX.read_text(encoding="utf-8"))
        if state.get("payload", {}).get("orchestration_run_id") == payload.get("orchestration_run_id"):
            return state
    except (OSError, json.JSONDecodeError):
        pass
    return {"status": "Ready to publish"}
