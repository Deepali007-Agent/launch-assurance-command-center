from __future__ import annotations

from collections import defaultdict
from typing import Any

from .calculation_policy import POLICY
from .executive_orchestrator import ExecutiveOrchestrator

QUALITY_AGENTS = {"CATALOG_QUALITY_AGENT", "POLICY_VALIDATION_AGENT"}
ATTRIBUTE_FIELDS = ("product_name", "brand", "description", "image_url", "colour", "size", "material")
SEVERITY_WEIGHT = {
    "CRITICAL": POLICY.critical_revenue_factor,
    "WARNING": POLICY.warning_revenue_factor,
    "NONE": 0.0,
}
RECOVERY_RATE = {
    "CRITICAL": POLICY.critical_recovery_rate,
    "WARNING": POLICY.warning_recovery_rate,
    "NONE": 0.0,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def _source(item: dict[str, Any], key: str, default: Any = None) -> Any:
    value = item.get(key)
    if value not in (None, ""):
        return value
    return (item.get("source_record") or {}).get(key, default)


def _latest_by_key(records: list[dict[str, Any]], entity_key: str, secondary_key: str | None = None) -> dict:
    latest = {}
    for record in records:
        key = (record.get(entity_key), record.get(secondary_key)) if secondary_key else record.get(entity_key)
        latest[key] = record
    return latest


def build_intelligence_from_records(
    items: list[dict[str, Any]], assessments: list[dict[str, Any]], decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create one auditable intelligence contract consumed by every leadership view."""
    latest_assessments = _latest_by_key(assessments, "entity_id", "agent_name")
    latest_decisions = _latest_by_key(decisions, "sku")
    findings_by_sku: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (sku, agent), assessment in latest_assessments.items():
        if agent in QUALITY_AGENTS:
            findings_by_sku[sku].extend(assessment.get("findings") or [])

    sku_rows = []
    actual_revenue_inputs = 0
    for item in items:
        sku = item["sku"]
        findings = findings_by_sku.get(sku, [])
        critical = any(f.get("severity") == "CRITICAL" for f in findings)
        warning = any(f.get("severity") == "WARNING" for f in findings)
        severity = "CRITICAL" if critical else "WARNING" if warning else "NONE"
        source_monthly_sales = _source(item, "monthly_sales")
        units_sold = _number(_source(item, "units_sold"), 0)
        price = _number(item.get("price"), 0)
        if source_monthly_sales not in (None, ""):
            monthly_revenue = _number(source_monthly_sales)
            actual_revenue_inputs += 1
        elif units_sold > 0:
            monthly_revenue = price * units_sold
            actual_revenue_inputs += 1
        else:
            monthly_revenue = price * POLICY.fallback_monthly_units
        affected_fields = sorted({str(f.get("field") or "general") for f in findings})
        distinct_defects = len([field for field in affected_fields if field != "general"])
        factor_cap = POLICY.critical_revenue_factor_cap if severity == "CRITICAL" else POLICY.warning_revenue_factor_cap
        severity_factor = min(
            factor_cap,
            SEVERITY_WEIGHT[severity] + max(0, distinct_defects - 1) * POLICY.extra_defect_uplift,
        ) if severity != "NONE" else 0.0
        revenue_at_risk = monthly_revenue * severity_factor
        expected_recovery = revenue_at_risk * RECOVERY_RATE[severity]
        completeness = sum(bool(str(item.get(field) or "").strip()) for field in ATTRIBUTE_FIELDS) / len(ATTRIBUTE_FIELDS) * 100
        content_risk = sum(POLICY.cx_field_weights.get(field, 0) for field in set(affected_fields))
        return_rate = _number(_source(item, "return_rate"), 0)
        rating = _number(_source(item, "rating"), POLICY.cx_rating_target)
        vendor_sla = _number(_source(item, "vendor_sla"), POLICY.group_sla_target_pct)
        gross_margin_pct = _number(_source(item, "gross_margin_pct"), POLICY.fallback_gross_margin_pct)
        return_risk = min(POLICY.cx_return_cap, max(0.0, return_rate - POLICY.cx_return_baseline_pct) * POLICY.cx_return_multiplier)
        rating_risk = min(POLICY.cx_rating_cap, max(0.0, POLICY.cx_rating_target - rating) * POLICY.cx_rating_multiplier)
        cx_score = min(100.0, content_risk + return_risk + rating_risk)
        decision = latest_decisions.get(sku, {})
        sku_rows.append({
            "sku": sku, "product": item.get("product_name") or "—", "vendor_id": item.get("vendor_id") or "—",
            "vendor": item.get("vendor_name") or item.get("vendor_id") or "Unknown vendor",
            "division": _source(item, "division", item.get("category") or "Unknown"),
            "category": item.get("category") or "Unknown", "severity": severity,
            "readiness": _number(decision.get("composite_readiness"), 100),
            "attribute_completeness": round(completeness, 1), "affected_fields": affected_fields,
            "monthly_revenue": round(monthly_revenue, 2), "revenue_at_risk": round(revenue_at_risk, 2),
            "expected_recovery": round(expected_recovery, 2), "cx_risk_score": round(cx_score, 1),
            "residual_revenue_risk": round(revenue_at_risk - expected_recovery, 2),
            "gross_margin_pct": round(gross_margin_pct, 1),
            "margin_at_risk": round(revenue_at_risk * gross_margin_pct / 100, 2),
            "expected_margin_recovery": round(expected_recovery * gross_margin_pct / 100, 2),
            "distinct_defects": distinct_defects, "severity_factor": round(severity_factor * 100, 1),
            "return_rate": round(return_rate, 1), "rating": round(rating, 1),
            "vendor_sla": round(vendor_sla, 1), "currency": "INR",
            "owner": _source(item, "business_owner", "Catalog Operations"),
        })

    total = len(sku_rows)
    critical_count = sum(r["severity"] == "CRITICAL" for r in sku_rows)
    warning_count = sum(r["severity"] == "WARNING" for r in sku_rows)
    clean_count = total - critical_count - warning_count
    attribute_completeness = round(sum(r["attribute_completeness"] for r in sku_rows) / total, 1) if total else 0.0
    readiness = round(sum(r["readiness"] for r in sku_rows) / total, 1) if total else 0.0
    health_score = round(max(0.0, min(100.0,
        readiness * POLICY.health_readiness_weight + attribute_completeness * POLICY.health_completeness_weight +
        (100 - (critical_count / total * 100 if total else 0)) * POLICY.health_blocker_free_weight
    )), 1) if total else 0.0

    def grouped_rows(group_key: str, owner_default: str) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in sku_rows:
            groups[str(row[group_key])].append(row)
        result = []
        total_risk = sum(r["revenue_at_risk"] for r in sku_rows) or 1.0
        for name, rows in groups.items():
            count = len(rows)
            affected = [r for r in rows if r["severity"] != "NONE"]
            critical = [r for r in rows if r["severity"] == "CRITICAL"]
            risk = sum(r["revenue_at_risk"] for r in rows)
            recovery = sum(r["expected_recovery"] for r in rows)
            affected_rate = len(affected) / count * 100 if count else 0
            critical_rate = len(critical) / count * 100 if count else 0
            # Average the source SLA across the rows in either grouping. This keeps
            # division risk sensitive to the actual vendor mix serving that division.
            sla = sum(r["vendor_sla"] for r in rows) / count if count else 95.0
            average_return = sum(r["return_rate"] for r in rows) / count if count else 0.0
            exposure_share = risk / total_risk * 100
            # Risk is intentionally comparable across vendors/divisions:
            # 30% defect rate, 25% critical rate, 20% SLA, 10% returns, 15% exposure concentration.
            risk_score = min(100.0,
                affected_rate * POLICY.group_affected_weight + critical_rate * POLICY.group_critical_weight +
                min(100.0, max(0.0, POLICY.group_sla_target_pct - sla) / POLICY.group_sla_full_risk_shortfall * 100) * POLICY.group_sla_weight +
                min(100.0, max(0.0, average_return - POLICY.group_return_baseline_pct) / POLICY.group_return_full_risk_gap * 100) * POLICY.group_return_weight +
                min(100.0, exposure_share * 4) * POLICY.group_exposure_weight
            )
            top_fields: dict[str, int] = defaultdict(int)
            for row in affected:
                for field in row["affected_fields"]:
                    top_fields[field] += 1
            root_cause = max(top_fields, key=top_fields.get) if top_fields else "No material defect"
            priority = "P1" if risk_score >= POLICY.group_high_threshold else "P2" if risk_score >= POLICY.group_medium_threshold else "P3"
            result.append({
                group_key: name, "submitted_skus": count, "affected_skus": len(affected),
                "critical_skus": len(critical), "affected_rate": round(affected_rate, 1),
                "risk_score": round(risk_score, 1), "risk_level": "High" if risk_score >= POLICY.group_high_threshold else "Medium" if risk_score >= POLICY.group_medium_threshold else "Low",
                "root_cause": root_cause.replace("_", " ").title(), "revenue_at_risk": round(risk, 2),
                "expected_recovery": round(recovery, 2), "priority": priority,
                "sla_compliance": round(sla, 1), "average_return_rate": round(average_return, 1),
                "exposure_share": round(exposure_share, 1),
                "owner": owner_default, "recommended_action": f"Correct {root_cause.replace('_', ' ')} defects and revalidate affected SKUs",
            })
        return sorted(result, key=lambda r: (r["priority"], -r["risk_score"], -r["revenue_at_risk"]))

    vendor_rows = grouped_rows("vendor", "Vendor Operations")
    division_rows = grouped_rows("division", "Division / Merchandising Lead")
    revenue_at_risk = round(sum(r["revenue_at_risk"] for r in sku_rows), 2)
    expected_recovery = round(sum(r["expected_recovery"] for r in sku_rows), 2)
    residual_revenue_risk = round(sum(r["residual_revenue_risk"] for r in sku_rows), 2)
    margin_at_risk = round(sum(r["margin_at_risk"] for r in sku_rows), 2)
    expected_margin_recovery = round(sum(r["expected_margin_recovery"] for r in sku_rows), 2)
    critical_revenue_at_risk = round(sum(r["revenue_at_risk"] for r in sku_rows if r["severity"] == "CRITICAL"), 2)
    total_monthly_revenue = round(sum(r["monthly_revenue"] for r in sku_rows), 2)
    cx_affected = [r for r in sku_rows if r["cx_risk_score"] > 0]
    cx_risk = round(sum(r["cx_risk_score"] for r in sku_rows) / total, 1) if total else 0.0
    top_vendor = vendor_rows[0] if vendor_rows else {}
    top_division = division_rows[0] if division_rows else {}
    critical_rate = critical_count / total * 100 if total else 0.0
    critical_exposure_pct = critical_revenue_at_risk / total_monthly_revenue * 100 if total_monthly_revenue else 0.0
    if critical_count and (
        critical_rate >= POLICY.portfolio_hold_critical_rate_pct
        or critical_exposure_pct >= POLICY.portfolio_hold_critical_exposure_pct
    ):
        catalog_decision = "HOLD"
        decision_scope = "Portfolio"
        decision_reason = "Critical SKU rate or critical financial exposure exceeds the governed portfolio threshold."
    elif critical_count:
        catalog_decision = "PARTIAL HOLD"
        decision_scope = "Affected SKUs and scopes"
        decision_reason = "Critical SKUs are quarantined while clean SKUs may continue to approval."
    elif warning_count:
        catalog_decision = "CONDITIONAL GO"
        decision_scope = "Warning-only SKUs"
        decision_reason = "No critical blockers remain; warnings require acceptance or correction."
    else:
        catalog_decision = "GO"
        decision_scope = "Portfolio"
        decision_reason = "No governed quality blockers remain."
    confidence = "High" if total and actual_revenue_inputs / total >= 0.8 else "Medium" if actual_revenue_inputs else "Modeled"
    top_actions = []
    for row in (vendor_rows + division_rows):
        if row["affected_skus"]:
            top_actions.append({
                "priority": row["priority"], "owner": row["owner"], "action": row["recommended_action"],
                "scope": row.get("vendor") or row.get("division"), "revenue_at_risk": row["revenue_at_risk"],
                "expected_recovery": row["expected_recovery"],
            })
    top_actions = sorted(top_actions, key=lambda r: (r["priority"], -r["revenue_at_risk"]))[:5]

    payload = {
        "contract_version": "catalog-intelligence-2.0",
        "policy": POLICY.as_contract(),
        "catalog": {"total_skus": total, "clean_skus": clean_count, "warning_skus": warning_count,
                    "critical_skus": critical_count, "readiness": readiness,
                    "attribute_completeness": attribute_completeness, "health_score": health_score,
                    "decision": catalog_decision, "decision_scope": decision_scope,
                    "decision_reason": decision_reason, "critical_rate": round(critical_rate, 1),
                    "critical_exposure_pct": round(critical_exposure_pct, 1)},
        "vendor": vendor_rows, "division": division_rows, "sku": sku_rows,
        "customer": {"affected_skus": len(cx_affected), "risk_score": cx_risk,
                     "risk_level": "High" if cx_risk >= POLICY.cx_high_threshold else "Medium" if cx_risk >= POLICY.cx_medium_threshold else "Low",
                     "revenue_at_risk": round(sum(r["revenue_at_risk"] for r in cx_affected), 2),
                     "formula": "Content risk (image 30, description 25, title 20, brand 12, size/material 10, colour 8) + return-rate risk up to 20 + rating risk up to 15; capped at 100."},
        "revenue": {"revenue_at_risk": revenue_at_risk, "expected_recovery": expected_recovery,
                    "residual_revenue_risk": residual_revenue_risk, "margin_at_risk": margin_at_risk,
                    "expected_margin_recovery": expected_margin_recovery,
                    "critical_revenue_at_risk": critical_revenue_at_risk,
                    "total_monthly_revenue": total_monthly_revenue,
                    "currency": "INR",
                    "recovery_rate": round(expected_recovery / revenue_at_risk * 100, 1) if revenue_at_risk else 0.0,
                    "confidence": confidence, "actual_input_coverage": round(actual_revenue_inputs / total * 100, 1) if total else 0.0,
                    "formula": "Monthly revenue in INR × governed severity factor. Base factors are Critical 35% and Warning 12%; each additional distinct defect adds 5 percentage points, capped at 55%/25%. Recovery uses 55%/70% respectively.",
                    "fallback": "When monthly_sales or units_sold are absent, monthly revenue is modeled as price × 10 units; gross margin defaults to 35% when absent."},
        "executive": {"decision": catalog_decision, "top_risk_vendor": top_vendor.get("vendor", "—"),
                      "top_risk_division": top_division.get("division", "—"), "top_actions": top_actions,
                      "revenue_at_risk": revenue_at_risk, "expected_recovery": expected_recovery,
                      "owner": top_actions[0]["owner"] if top_actions else "Catalog Operations"},
    }
    orchestration = ExecutiveOrchestrator().compose(payload, items, assessments, decisions)
    payload["orchestration"] = orchestration
    payload["executive"].update(
        decision=orchestration["decision"], decision_reason=orchestration["decision_reason"],
        synchronization=orchestration["synchronization"], provenance=orchestration["provenance"],
        governed_actions=orchestration["actions"], conflicts_resolved=orchestration["conflicts_resolved"],
    )
    return payload


def build_intelligence(repository) -> dict[str, Any]:
    items, assessments, decisions = (
        repository.list_current_items(), repository.list_assessments(), repository.list_decisions()
    )
    payload = build_intelligence_from_records(items, assessments, decisions)
    orchestration = ExecutiveOrchestrator(repository).compose(payload, items, assessments, decisions)
    payload["orchestration"] = orchestration
    payload["executive"].update(
        decision=orchestration["decision"], decision_reason=orchestration["decision_reason"],
        synchronization=orchestration["synchronization"], provenance=orchestration["provenance"],
        governed_actions=orchestration["actions"], conflicts_resolved=orchestration["conflicts_resolved"],
    )
    return payload
