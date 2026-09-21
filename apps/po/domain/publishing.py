"""Governed, idempotent publication of PO Intelligence results."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.contracts import RunMetadata


OUTBOX = Path("data/po_publication_outbox.json")
SCHEMA = "retail-intelligence.po.v1"


def build_publication(
    metadata: RunMetadata,
    results: list[dict[str, Any]],
    financial: dict[str, Any],
    vendor_scorecard: list[dict[str, Any]],
    division_performance: list[dict[str, Any]],
    sla: dict[str, Any],
    actions: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    ready = sum(row.get("status") == "PASS" for row in results)
    warning = sum(row.get("status") == "WARN" for row in results)
    blocked = sum(row.get("status") == "FAIL" for row in results)
    total = len(results)
    readiness = round(sum(float(row.get("readiness") or 0) for row in results) / total, 1) if total else 0.0
    # A new validation/cycle or changed commercial evidence must never reuse
    # acknowledgement of an older assessment with the same pass/fail counts.
    fingerprint = hashlib.sha256(json.dumps({
        "cycle": os.getenv("RETAIL_BUSINESS_CYCLE_ID", "").strip(),
        "run": metadata.run_id, "results": results, "financial": financial,
    }, sort_keys=True, default=str).encode()).hexdigest()[:16].upper()
    health = [{
        "po_id": row.get("po_id"),
        "sku": row.get("sku"),
        "vendor_id": row.get("vendor_id") or row.get("vendor"),
        "status": row.get("status"),
        "readiness": float(row.get("readiness") or 0),
        "severity": "CRITICAL" if row.get("status") == "FAIL" else "WARNING" if row.get("status") == "WARN" else "NONE",
        "issues": list(row.get("errors") or []) + list(row.get("warnings") or []),
    } for row in results]
    decision = "HOLD" if blocked else "CONDITIONAL" if warning else "READY"
    return {
        "schema": SCHEMA,
        "evaluator_type": "deterministic",
        "input_contract_version": "retail-source-input-1.0",
        "evidence_contract_version": "retail-cycle-controls-2.0",
        "schema_version": "1.0",
        "source": "PO_INTELLIGENCE",
        "business_cycle_id": os.getenv("RETAIL_BUSINESS_CYCLE_ID", "").strip(),
        "orchestration_run_id": f"PO-ORCH-{fingerprint}",
        "dataset_run_ids": [metadata.run_id],
        "policy_version": "po-validation-policy-1.0",
        "synchronization_status": "VERIFIED",
        "published_at": datetime.now(timezone.utc).isoformat(),
        "executive_decision": {
            "decision": decision,
            "reason": f"{blocked} blocked and {warning} warning PO lines across {total} assessed lines.",
        },
        "po_intelligence": {
            "total_lines": total,
            "ready_lines": ready,
            "warning_lines": warning,
            "blocked_lines": blocked,
            "readiness_score": readiness,
            "financial_exposure": float(financial.get("at_risk_rev") or 0),
            "currency": "INR",
        },
        "po_health": health,
        "financial_impact": financial,
        "vendor_scorecard": vendor_scorecard,
        "division_performance": division_performance,
        "sla": sla,
        "leadership_actions": actions,
        "po_decisions": decisions,
        "provenance": {
            "source_agent": "PO_INTELLIGENCE",
            "source_run_id": metadata.run_id,
            "source_file": metadata.source_file,
            "row_count": metadata.row_count,
            "validated_at": metadata.validated_at,
        },
    }


def publish(payload: dict[str, Any], *, attempts: int = 3) -> dict[str, Any]:
    endpoint = os.getenv("RETAIL_INTELLIGENCE_API_URL", "").strip()
    token = os.getenv("RETAIL_INTELLIGENCE_API_TOKEN", "").strip()
    if not endpoint or not token:
        return {"status": "READY_TO_PUBLISH", "message": "Retail Intelligence destination is not configured."}
    publication_id = f"PUB-PO-{payload['orchestration_run_id'].removeprefix('PO-ORCH-')}"
    existing = publication_state(payload)
    if existing.get("status") == "PUBLISHED":
        return existing
    last_error = ""
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, default=str).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Idempotency-Key": publication_id,
                "X-PO-Intelligence-Schema": SCHEMA,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                acknowledgement = json.loads(response.read().decode())
            state = {
                "publication_id": publication_id,
                "status": "PUBLISHED",
                "attempt_count": attempt,
                "payload": payload,
                "acknowledgement": acknowledgement,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            OUTBOX.parent.mkdir(parents=True, exist_ok=True)
            OUTBOX.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
            return state
        except (OSError, urllib.error.URLError, ValueError) as error:
            last_error = f"{type(error).__name__}: {error}"
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
    return {"status": "FAILED", "attempt_count": attempts, "last_error": last_error, "payload": payload}


def publication_state(payload: dict[str, Any]) -> dict[str, Any]:
    if OUTBOX.exists():
        try:
            state = json.loads(OUTBOX.read_text(encoding="utf-8"))
            if state.get("payload", {}).get("orchestration_run_id") == payload.get("orchestration_run_id"):
                return state
        except (OSError, json.JSONDecodeError):
            pass
    return {"status": "READY_TO_PUBLISH"}
