"""Combined, auditable Vendor + Item Onboarding intelligence contract."""
from __future__ import annotations

from datetime import date, timedelta
import pandas as pd

from item_onboarding import assess_items


def build_onboarding_intelligence(vendors: pd.DataFrame, assessments: pd.DataFrame, item_frame: pd.DataFrame) -> dict:
    vendor_frame = vendors.drop_duplicates("vendor_id", keep="last").copy() if not vendors.empty else pd.DataFrame()
    vendor_findings = []
    if not assessments.empty:
        for _, assessment in assessments.iterrows():
            for finding in assessment.get("findings", []) or []:
                vendor_findings.append({"vendor_id": assessment["vendor_id"], **finding})
    finding_frame = pd.DataFrame(vendor_findings)
    critical_vendor_ids = set(finding_frame.loc[finding_frame.get("severity", pd.Series(dtype=str)).eq("Critical"), "vendor_id"]) if not finding_frame.empty else set()
    warning_vendor_ids = set(finding_frame.loc[finding_frame.get("severity", pd.Series(dtype=str)).eq("Warning"), "vendor_id"]) - critical_vendor_ids if not finding_frame.empty else set()
    vendor_rows = []
    for _, vendor in vendor_frame.iterrows():
        vendor_id = str(vendor.get("vendor_id"))
        severity = "Critical" if vendor_id in critical_vendor_ids else "Warning" if vendor_id in warning_vendor_ids else "None"
        related = finding_frame[finding_frame["vendor_id"].eq(vendor_id)].copy() if not finding_frame.empty else pd.DataFrame()
        if not related.empty:
            related["_severity_rank"] = related["severity"].map({"Critical": 0, "Warning": 1}).fillna(2)
            related = related.sort_values("_severity_rank")
        root = related.iloc[0].get("field") if not related.empty else "None"
        owner = related.iloc[0].get("owner") if not related.empty else "Approval Team"
        vendor_rows.append({
            "Vendor ID": vendor_id, "Vendor": vendor.get("legal_name") or vendor_id,
            "Vendor status": "Blocked" if severity == "Critical" else "Conditional" if severity == "Warning" else "Ready",
            "Severity": severity, "Root cause": str(root).replace("_", " ").title(),
            "Accountable team": owner, "Current stage": vendor.get("status", "Received"),
            "Age (days)": float(vendor.get("age_days") or 0),
            "Planned value": pd.to_numeric(vendor.get("planned_purchase_value"), errors="coerce"),
            "Value currency": str(vendor.get("value_currency") or vendor.get("currency") or "").upper(),
        })
    vendor_health = pd.DataFrame(vendor_rows)

    item_detail, item_summary = assess_items(item_frame)
    rank = {"Critical": 0, "Warning": 1, "None": 2}
    item_detail["_rank"] = item_detail["Highest severity"].map(rank).fillna(3)
    item_unique = item_detail.sort_values("_rank").drop_duplicates("SKU", keep="first").drop(columns="_rank")
    vendor_status = vendor_health.set_index("Vendor ID")["Vendor status"].to_dict() if not vendor_health.empty else {}
    vendor_name = vendor_health.set_index("Vendor ID")["Vendor"].to_dict() if not vendor_health.empty else {}
    item_unique["Linked vendor"] = item_unique["Vendor ID"].map(vendor_name).fillna("Vendor not found")
    item_unique["Vendor onboarding status"] = item_unique["Vendor ID"].map(vendor_status).fillna("Unmatched")
    item_unique["Effective status"] = item_unique["Status"]
    vendor_block_mask = item_unique["Vendor onboarding status"].eq("Blocked")
    item_unique.loc[vendor_block_mask, "Effective status"] = "Blocked by vendor"
    conditional_mask = item_unique["Vendor onboarding status"].eq("Conditional") & item_unique["Effective status"].eq("Approval ready")
    item_unique.loc[conditional_mask, "Effective status"] = "Conditional on vendor"
    unmatched_mask = item_unique["Vendor onboarding status"].eq("Unmatched") & item_unique["Vendor ID"].ne("—")
    item_unique.loc[unmatched_mask & item_unique["Effective status"].eq("Approval ready"), "Effective status"] = "Pending reconciliation"

    linked_items = int(item_unique["Vendor ID"].isin(vendor_status).sum())
    vendor_blocked_items = int(item_unique["Effective status"].eq("Blocked by vendor").sum())
    unmatched_items = int(item_unique["Vendor onboarding status"].eq("Unmatched").sum())
    effective_ready = int(item_unique["Effective status"].eq("Approval ready").sum())
    effective_warning = int(item_unique["Effective status"].isin(["Review warnings", "Conditional on vendor"]).sum())
    effective_blocked = int(item_unique["Effective status"].isin(["Correction required", "Blocked by vendor"]).sum())
    vendor_total = len(vendor_health)
    vendor_ready = int(vendor_health["Vendor status"].eq("Ready").sum()) if vendor_total else 0
    vendor_warning = int(vendor_health["Vendor status"].eq("Conditional").sum()) if vendor_total else 0
    vendor_blocked = int(vendor_health["Vendor status"].eq("Blocked").sum()) if vendor_total else 0
    vendor_readiness = 100 * (vendor_ready + 0.5 * vendor_warning) / vendor_total if vendor_total else 0
    item_readiness = 100 * (effective_ready + 0.5 * effective_warning) / len(item_unique) if len(item_unique) else 0
    combined_readiness = vendor_readiness * 0.40 + item_readiness * 0.60
    vendor_decision = "HOLD" if vendor_blocked else "CONDITIONAL" if vendor_warning else "GO"
    own_item_blocked = int(item_unique["Status"].eq("Correction required").sum())
    own_item_warning = int(item_unique["Status"].eq("Review warnings").sum())
    item_decision = "HOLD" if own_item_blocked else "CONDITIONAL" if own_item_warning else "GO"
    linkage_coverage = 100 * linked_items / len(item_unique) if len(item_unique) else 0
    decision = "HOLD" if vendor_blocked or own_item_blocked else "PENDING RECONCILIATION" if unmatched_items else "CONDITIONAL GO" if vendor_warning or own_item_warning else "GO"

    measurable = vendor_health[vendor_health["Value currency"].eq("INR") & vendor_health["Planned value"].notna()] if not vendor_health.empty else pd.DataFrame()
    blocked_vendor_ids = set(vendor_health.loc[vendor_health["Vendor status"].eq("Blocked"), "Vendor ID"]) if not vendor_health.empty else set()
    blocked_value = float(measurable.loc[measurable["Vendor ID"].isin(blocked_vendor_ids), "Planned value"].sum()) if not measurable.empty else 0.0
    value_coverage = 100 * len(measurable) / vendor_total if vendor_total else 0.0

    vendor_item = item_unique.groupby(["Vendor ID", "Linked vendor", "Vendor onboarding status"], as_index=False).agg(
        Submitted_items=("SKU", "nunique"), Item_ready=("Effective status", lambda values: sum(value == "Approval ready" for value in values)),
        Items_blocked=("Effective status", lambda values: sum(value in {"Correction required", "Blocked by vendor"} for value in values)),
        Items_conditional=("Effective status", lambda values: sum(value in {"Review warnings", "Conditional on vendor"} for value in values)),
        Reconciliation_exceptions=("Effective status", lambda values: sum(value == "Pending reconciliation" for value in values)),
    )
    vendor_item = vendor_item.merge(vendor_health[["Vendor ID", "Root cause", "Accountable team", "Planned value", "Value currency"]], on="Vendor ID", how="left") if not vendor_health.empty else vendor_item
    vendor_item = vendor_item.sort_values(["Items_blocked", "Submitted_items"], ascending=False)

    action_rows = []
    for _, row in vendor_health[vendor_health["Vendor status"].ne("Ready")].iterrows():
        action_rows.append({"Priority": "P1" if row["Vendor status"] == "Blocked" else "P2", "Scope": row["Vendor"], "Record type": "Vendor", "Records affected": 1,
                            "Root cause": row["Root cause"], "Accountable team": row["Accountable team"], "Due date": (date.today() + timedelta(days=3 if row["Vendor status"] == "Blocked" else 7)).isoformat(),
                            "Status": "Open", "Value blocked (INR)": row["Planned value"] if row["Value currency"] == "INR" else 0,
                            "Required action": "Correct vendor evidence and revalidate"})
    for _, row in item_unique[item_unique["Effective status"].ne("Approval ready")].iterrows():
        priority = "P1" if row["Effective status"] in {"Correction required", "Blocked by vendor"} else "P2"
        action_rows.append({"Priority": priority, "Scope": row["SKU"], "Record type": "Item", "Records affected": 1,
                            "Root cause": "Vendor onboarding" if row["Effective status"] == "Blocked by vendor" else "Vendor ID reconciliation" if row["Effective status"] == "Pending reconciliation" else row["Affected attributes"],
                            "Accountable team": "Vendor Operations" if row["Effective status"] == "Blocked by vendor" else "Onboarding Data Governance" if row["Effective status"] == "Pending reconciliation" else row["Accountable team"],
                            "Due date": (date.today() + timedelta(days=3 if priority == "P1" else 7)).isoformat(), "Status": "Open",
                            "Value blocked (INR)": 0, "Required action": "Resolve linked vendor blocker" if row["Effective status"] == "Blocked by vendor" else "Match the item vendor ID to the validated vendor dataset" if row["Effective status"] == "Pending reconciliation" else row["Required action"]})
    action_detail = pd.DataFrame(action_rows)
    action_summary = action_detail.groupby(["Priority", "Record type", "Root cause", "Accountable team", "Due date", "Status", "Required action"], as_index=False).agg(
        Records_affected=("Records affected", "sum"), Value_blocked_INR=("Value blocked (INR)", "sum")
    ) if not action_detail.empty else pd.DataFrame()

    return {
        "decision": decision, "combined_readiness": round(combined_readiness, 1),
        "vendor": {"total": vendor_total, "ready": vendor_ready, "warning": vendor_warning, "blocked": vendor_blocked, "readiness": round(vendor_readiness, 1), "decision": vendor_decision},
        "item": {"total": len(item_unique), "ready": effective_ready, "warning": effective_warning, "blocked": effective_blocked, "readiness": round(item_readiness, 1),
                 "linked": linked_items, "unmatched": unmatched_items, "blocked_by_vendor": vendor_blocked_items, "decision": item_decision,
                 "own_blocked": own_item_blocked, "own_warning": own_item_warning},
        "reconciliation": {"linked": linked_items, "unmatched": unmatched_items, "coverage_pct": round(linkage_coverage, 1), "status": "Complete" if unmatched_items == 0 else "Exceptions found"},
        "blocked_value_inr": blocked_value, "value_coverage_pct": round(value_coverage, 1),
        "vendor_health": vendor_health, "item_health": item_unique, "vendor_item": vendor_item,
        "actions": action_summary, "action_detail": action_detail,
        "assumptions": {"vendor_weight": 0.40, "item_weight": 0.60,
                        "decision_rule": "HOLD when either source has critical blockers; CONDITIONAL GO for warning-only exposure; GO only when both are clear."},
    }
