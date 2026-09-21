from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any

from .calculation_policy import POLICY


REQUIRED_AGENTS = {"CATALOG_QUALITY_AGENT", "POLICY_VALIDATION_AGENT"}


def _action_id(scope_type: str, scope: str, root_cause: str) -> str:
    value = f"{scope_type}|{scope}|{root_cause}".lower().encode("utf-8")
    return f"ACT-{sha256(value).hexdigest()[:12].upper()}"


class ExecutiveOrchestrator:
    """Publish one synchronized, traceable executive decision package.

    Domain modules remain calculation authorities. This layer validates their
    freshness, resolves cross-domain signals and governs leadership actions.
    """

    contract_version = "executive-orchestration-1.0"

    def __init__(self, repository=None):
        self.repository = repository

    @staticmethod
    def _synchronization(items: list[dict[str, Any]], assessments: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
        expected = {str(item.get("sku")): str(item.get("workflow_run_id") or "") for item in items}
        assessment_pairs = {
            (str(value.get("entity_id")), str(value.get("agent_name")), str(value.get("workflow_run_id") or ""))
            for value in assessments
        }
        decision_pairs = {(str(value.get("sku")), str(value.get("workflow_run_id") or "")) for value in decisions}
        has_run_metadata = bool(expected) and all(expected.values())
        missing: list[str] = []
        if has_run_metadata:
            for sku, run_id in expected.items():
                for agent in REQUIRED_AGENTS:
                    if (sku, agent, run_id) not in assessment_pairs:
                        missing.append(f"{sku}:{agent}")
                if (sku, run_id) not in decision_pairs:
                    missing.append(f"{sku}:DOMAIN_DECISION")
        run_ids = sorted({run_id for run_id in expected.values() if run_id})
        return {
            "status": "VERIFIED" if has_run_metadata and not missing else "LEGACY_UNVERIFIED" if not has_run_metadata else "BLOCKED",
            "is_synchronized": bool(has_run_metadata and not missing), "run_ids": run_ids,
            "portfolio_mode": "MULTI_RUN_CURRENT_PORTFOLIO" if len(run_ids) > 1 else "SINGLE_RUN",
            "missing_inputs": missing, "checked_skus": len(expected),
        }

    @staticmethod
    def _domain_contracts(payload: dict[str, Any], run_ids: list[str]) -> dict[str, Any]:
        shared = {"policy_version": POLICY.version, "run_ids": run_ids, "currency": POLICY.currency}
        return {
            "catalog": {**shared, "authority": "CATALOG_INTELLIGENCE", "kpis": payload["catalog"], "confidence": "Governed"},
            "vendor": {**shared, "authority": "VENDOR_INTELLIGENCE", "records": payload["vendor"], "confidence": "Governed" if payload["vendor"] else "Insufficient data"},
            "division": {**shared, "authority": "DIVISION_PERFORMANCE", "records": payload["division"], "confidence": "Governed" if payload["division"] else "Insufficient data"},
            "revenue": {**shared, "authority": "REVENUE_IMPACT", "kpis": payload["revenue"], "confidence": payload["revenue"].get("confidence", "Modeled")},
            "customer": {**shared, "authority": "CUSTOMER_EXPERIENCE", "kpis": payload["customer"], "confidence": "Governed"},
        }

    @staticmethod
    def _resolve_decision(payload: dict[str, Any], sync: dict[str, Any]) -> tuple[str, str, list[str]]:
        if sync["status"] == "BLOCKED":
            return "NOT AVAILABLE", "Underlying outputs are stale or incomplete for current SKU versions.", []
        decision, reason = payload["catalog"]["decision"], payload["catalog"]["decision_reason"]
        conflicts: list[str] = []
        if decision == "GO" and payload["customer"].get("risk_level") == "High":
            conflicts.append("Catalog cleared but customer-experience risk is high.")
            decision, reason = "CONDITIONAL GO", "Customer-experience risk requires governed acceptance before release."
        if decision == "GO" and any(row.get("risk_level") == "High" for row in payload["vendor"]):
            conflicts.append("Catalog cleared but at least one vendor risk tier is high.")
            decision, reason = "CONDITIONAL GO", "High vendor operating risk requires leadership acceptance before release."
        return decision, reason, conflicts

    @staticmethod
    def _actions(payload: dict[str, Any], generated_at: datetime) -> list[dict[str, Any]]:
        actions = []
        for value in payload["executive"].get("top_actions", []):
            scope, action = str(value.get("scope") or "Portfolio"), str(value.get("action") or "Remediate catalog risk")
            priority = str(value.get("priority") or "P3")
            due_days = {"P1": 2, "P2": 5, "P3": 10}.get(priority, 10)
            actions.append({
                "action_id": _action_id("LEADERSHIP_SCOPE", scope, action), "scope": scope,
                "priority": priority, "owner": value.get("owner") or "Catalog Operations", "action": action,
                "status": "OPEN", "opened_at": generated_at.isoformat(),
                "due_at": (generated_at + timedelta(days=due_days)).isoformat(),
                "revenue_at_risk": value.get("revenue_at_risk", 0),
                "recovery_target": value.get("expected_recovery", 0), "currency": POLICY.currency,
                "closure_rule": "Close after the affected scope is revalidated and disappears from current priorities.",
            })
        return actions

    def compose(self, payload: dict[str, Any], items: list[dict[str, Any]], assessments: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc)
        sync = self._synchronization(items, assessments, decisions)
        decision, reason, conflicts = self._resolve_decision(payload, sync)
        actions = self._actions(payload, generated_at)
        if self.repository is not None:
            self.repository.synchronize_executive_actions(actions, sync["run_ids"])
            actions = self.repository.list_executive_actions(active_only=True)
        orchestration_fingerprint = json.dumps({
            "run_ids": sync["run_ids"], "policy": POLICY.version,
            "skus": sorted((str(item.get("sku")), int(item.get("revision_number") or 1)) for item in items),
        }, sort_keys=True).encode("utf-8")
        orchestration_run_id = f"ORCH-{sha256(orchestration_fingerprint).hexdigest()[:16].upper()}"
        return {
            "contract_version": self.contract_version, "generated_at": generated_at.isoformat(),
            "orchestration_run_id": orchestration_run_id,
            "policy_version": POLICY.version, "currency": POLICY.currency, "synchronization": sync,
            "domain_contracts": self._domain_contracts(payload, sync["run_ids"]),
            "decision": decision, "decision_reason": reason, "conflicts_resolved": conflicts, "actions": actions,
            "provenance": {"source_agents": sorted(REQUIRED_AGENTS), "source_run_ids": sync["run_ids"],
                "source_sku_count": len(items), "calculation_authorities": {
                    "catalog": "CATALOG_INTELLIGENCE", "vendor": "VENDOR_INTELLIGENCE",
                    "division": "DIVISION_PERFORMANCE", "revenue": "REVENUE_IMPACT", "customer": "CUSTOMER_EXPERIENCE"}},
        }
