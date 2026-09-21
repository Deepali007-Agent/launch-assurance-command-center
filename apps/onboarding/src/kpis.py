"""Governed KPI registry and deterministic calculations for Vendor IQ Pro."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import pandas as pd

from dates import parse_business_dates

OPEN_STATUSES = {
    "Received", "Structural Validation", "Information Review", "Compliance Review",
    "Commercial Review", "Approval Decision", "Correction Required", "On Hold",
    "Expired Documentation", "Renewal Required",
}
COMPLETED_STATUSES = {"Handoff Ready", "Created in System (Simulated)"}
EXCLUDED_STATUSES = {"Rejected"}
INTERNAL_STATUSES = {
    "Structural Validation", "Information Review", "Compliance Review", "Commercial Review",
    "Approval Decision", "On Hold",
}
VENDOR_STATUSES = {"Correction Required", "Expired Documentation", "Renewal Required"}


@dataclass(frozen=True)
class KPI:
    key: str
    name: str
    purpose: str
    numerator: str
    denominator: str
    eligible_population: str
    exclusions: str
    unit: str
    required_fields: str
    open_record_treatment: str
    owner: str
    target: str = ""


@dataclass(frozen=True)
class KPIResult:
    key: str
    value: float | int | None
    display: str
    measurable: bool
    numerator: float | int | None = None
    denominator: float | int | None = None
    explanation: str = ""


REGISTRY = [
    KPI("vendors_in_onboarding", "Vendors in onboarding", "Size the active operational pipeline", "Unique open vendor IDs", "Not applicable", "Latest vendor record", "Rejected and completed vendors", "vendors", "vendor_id, status", "Count open records", "Vendor Operations"),
    KPI("median_safe_activation_days", "Median time to safe activation", "Measure normal end-to-end journey time", "Median calendar days from valid submission to approval/handoff", "Measurable safely activated vendors", "Completed vendors with both timestamps", "Missing timestamps and rejected vendors", "days", "submitted_at, approval audit timestamp", "Open records excluded", "Vendor Operations", "Diagnostic until stage-level targets are approved"),
    KPI("first_pass_approval_rate", "First-pass approval rate", "Measure submission quality and avoided rework", "Approved vendors with revision 1", "Vendors with a governed approval event", "Approved vendors with revision evidence", "Vendors without approval evidence", "%", "vendor_id, revision, approval audit event", "Open vendors without approval are excluded", "Vendor Onboarding", "≥ 80%"),
    KPI("sla_attainment", "End-to-end target attainment", "Monitor timely safe activation after stage targets are governed", "Pending approved targets for vendor response, validation, compliance, commercial review, approval and handoff", "Not applicable", "Not yet measurable", "All records until stage-entry and exit timestamps are complete", "%", "complete stage transition timestamps", "Not calculated from total journey age", "Vendor Operations", "Pending stage-level SLA definition"),
    KPI("critical_blocker_rate", "Critical blocker rate", "Quantify control failures", "Unique vendors with unresolved critical findings", "Active vendors assessed", "Open latest vendor records", "Rejected and completed vendors", "%", "latest assessments, status", "Only current open exposure counted", "Risk & Compliance"),
    KPI("opportunity_awaiting_activation", "Business value awaiting activation", "Quantify expected purchasing value attached to open onboarding journeys", "Sum of planned purchase value for unique open vendors", "Not applicable", "Open vendors with value and base currency evidence", "Missing values and non-base-currency records", "GBP", "planned_purchase_value, value_currency, status", "Open measurable records included", "Commercial Operations"),
    KPI("opportunity_at_risk", "Business value blocked", "Prioritize critical blockers using expected purchasing value", "Unique open critical vendors' planned purchase value", "Total measurable open business value", "Open vendors with critical findings and GBP value", "Missing values and non-base-currency records", "GBP", "planned_purchase_value, value_currency, latest assessments", "Only current critical exposure counted", "Commercial Operations"),
    KPI("approvals_awaiting", "Approvals awaiting decision", "Expose human decision backlog", "Unique vendors in Approval Decision", "Not applicable", "Latest vendor record", "All other statuses", "vendors", "vendor_id, status", "Current queue only", "Approval Team"),
    KPI("post_approval_defect_rate", "Post-approval defect rate", "Guard activation quality", "Approved vendors later reopened or corrected", "Vendors with an approval event", "Vendors with auditable approval history", "No approval event", "%", "audit event history", "Completed and reopened records included", "Vendor Operations", "≤ 2%"),
    KPI("vendor_delay_share", "Vendor-attributable delay share", "Separate vendor waiting time from internal delay", "Age of open records awaiting vendor action", "Age of all open records with ownership", "Open vendors with measurable age", "Unowned or missing timestamp records", "%", "status, submitted_at", "Current-stage approximation until complete transition history exists", "Vendor Onboarding"),
    KPI("internal_delay_share", "Internal-attributable delay share", "Expose internal queue contribution", "Age of open records awaiting internal action", "Age of all open records with ownership", "Open vendors with measurable age", "Unowned or missing timestamp records", "%", "status, submitted_at", "Current-stage approximation until complete transition history exists", "Vendor Operations"),
    KPI("unowned_open_rate", "Unowned open-case rate", "Detect governance failures", "Open vendors without an accountable owner", "All open vendors", "Latest open vendor records", "Completed and rejected vendors", "%", "status, onboarding_owner", "Current queue only", "Vendor Operations", "0%"),
    KPI("average_revision_count", "Average revision count", "Measure rework and correction burden", "Sum of latest revision numbers", "Unique active and completed vendors", "Latest vendor records", "Rejected vendors", "revisions", "revision", "Open and completed records included", "Vendor Onboarding"),
    KPI("documents_expiring_90", "90-day document expiry exposure", "Protect continuity after onboarding", "Unique vendors with documents expiring in 0–90 days", "Vendors with valid parseable expiry dates", "Active and onboarding vendors requiring documents", "Missing or invalid expiry dates", "%", "document_expiry_date", "Open and completed active records included", "Compliance"),
    KPI("items_blocked", "Downstream items blocked", "Show catalog dependency waiting behind onboarding", "Sum of planned item count for open critical vendors", "Not applicable", "Open vendors with critical findings", "Missing planned item counts", "items", "planned_item_count, latest assessments", "Current critical exposure only", "Catalog Operations"),
]


def registry_frame() -> pd.DataFrame:
    return pd.DataFrame([asdict(metric) for metric in REGISTRY]).rename(columns={
        "name": "KPI", "purpose": "Business purpose", "numerator": "Numerator",
        "denominator": "Denominator", "eligible_population": "Eligible population",
        "exclusions": "Exclusions", "unit": "Unit", "required_fields": "Required evidence",
        "open_record_treatment": "Open-record treatment", "owner": "Business owner", "target": "Target",
    }).drop(columns=["key"])


def _result(key, value, display, measurable=True, numerator=None, denominator=None, explanation=""):
    return KPIResult(key, value, display, measurable, numerator, denominator, explanation)


def _rate(key, numerator, denominator, explanation=""):
    if not denominator:
        return _result(key, None, "Not measurable yet", False, numerator, denominator, explanation or "No eligible measurable records.")
    value = numerator / denominator
    return _result(key, value, f"{value:.0%}", True, numerator, denominator, explanation)


def calculate_kpis(vendors: pd.DataFrame, assessments: pd.DataFrame, audit: pd.DataFrame, now=None) -> dict[str, KPIResult]:
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    results: dict[str, KPIResult] = {}
    if vendors.empty:
        return {metric.key: _result(metric.key, None, "Not measurable yet", False, explanation="No vendor records loaded.") for metric in REGISTRY}

    frame = vendors.drop_duplicates("vendor_id", keep="last").copy()
    frame["status"] = frame.get("status", "Received").fillna("Received")
    frame["submitted_at"] = pd.to_datetime(frame.get("submitted_at"), errors="coerce", utc=True)
    frame["age_days"] = ((now - frame["submitted_at"]).dt.total_seconds() / 86400).clip(lower=0)
    open_vendors = frame[frame["status"].isin(OPEN_STATUSES)].copy()
    results["vendors_in_onboarding"] = _result("vendors_in_onboarding", len(open_vendors), f"{len(open_vendors):,}", explanation="Unique latest open vendor records.")

    latest = assessments.copy()
    if not latest.empty:
        latest = latest.sort_values("id").drop_duplicates(["vendor_id", "agent"], keep="last") if "id" in latest else latest.drop_duplicates(["vendor_id", "agent"], keep="last")
        critical_ids = set(latest.loc[latest["severity"].eq("Critical"), "vendor_id"])
        assessed_ids = set(latest["vendor_id"])
        cleared_ids = assessed_ids - critical_ids
    else:
        critical_ids, assessed_ids, cleared_ids = set(), set(), set()

    active_ids = set(open_vendors["vendor_id"])
    open_critical = active_ids & critical_ids
    results["critical_blocker_rate"] = _rate("critical_blocker_rate", len(open_critical), len(active_ids & assessed_ids), "Unique current critical vendors divided by assessed open vendors.")
    approval_events = pd.DataFrame()
    if not audit.empty:
        events = audit.copy()
        events["created_at"] = pd.to_datetime(events["created_at"], errors="coerce", utc=True)
        approval_events = events[events["event_type"].eq("Vendor approved")].sort_values("created_at").drop_duplicates("vendor_id", keep="first")
        completed = frame[frame["vendor_id"].isin(approval_events["vendor_id"])].merge(approval_events[["vendor_id", "created_at"]], on="vendor_id", how="inner")
        completed["activation_days"] = (completed["created_at"] - completed["submitted_at"]).dt.total_seconds() / 86400
        completed = completed[completed["activation_days"].notna() & completed["activation_days"].ge(0)]
    else:
        events = pd.DataFrame()
        completed = pd.DataFrame()
    if approval_events.empty:
        results["first_pass_approval_rate"] = _result("first_pass_approval_rate", None, "Not measurable yet", False, explanation="No governed approval events exist.")
    else:
        approved = frame[frame["vendor_id"].isin(approval_events["vendor_id"])]
        approved_revisions = pd.to_numeric(approved.get("revision"), errors="coerce")
        results["first_pass_approval_rate"] = _rate("first_pass_approval_rate", int(approved_revisions.eq(1).sum()), int(approved_revisions.notna().sum()), "Approved vendors on revision one divided by approved vendors with revision evidence.")
    if completed.empty:
        results["median_safe_activation_days"] = _result("median_safe_activation_days", None, "Not measurable yet", False, explanation="No vendor has both valid-submission and approval timestamps.")
        results["sla_attainment"] = _result("sla_attainment", None, "Not measurable yet", False, explanation="No completed measurable activation journeys.")
    else:
        median = float(completed["activation_days"].median())
        results["median_safe_activation_days"] = _result("median_safe_activation_days", median, f"{median:.1f} days", numerator=len(completed), explanation="Median across measurable approved vendors.")
        results["sla_attainment"] = _result("sla_attainment", None, "Not measurable yet", False, explanation="Stage-level SLA targets and complete transition timestamps are required; total journey age is not used as a substitute.")

    results["approvals_awaiting"] = _result("approvals_awaiting", int(frame["status"].eq("Approval Decision").sum()), f"{int(frame['status'].eq('Approval Decision').sum()):,}")
    if approval_events.empty or events.empty:
        results["post_approval_defect_rate"] = _result("post_approval_defect_rate", None, "Not measurable yet", False, explanation="No approval history exists.")
    else:
        reopened = events[events["event_type"].isin(["Correction requested", "Vendor placed on hold", "Vendor rejected"])].merge(approval_events[["vendor_id", "created_at"]], on="vendor_id", suffixes=("", "_approved"))
        reopened_ids = reopened.loc[reopened["created_at"] > reopened["created_at_approved"], "vendor_id"].nunique()
        results["post_approval_defect_rate"] = _rate("post_approval_defect_rate", reopened_ids, approval_events["vendor_id"].nunique(), "Approved vendors subsequently returned to correction, hold, or rejection.")

    values = pd.to_numeric(open_vendors.get("planned_purchase_value"), errors="coerce")
    currencies = open_vendors.get("value_currency", pd.Series("", index=open_vendors.index)).astype(str).str.upper()
    measurable_value = values.notna() & values.ge(0) & currencies.eq("GBP")
    opportunity = float(values[measurable_value].sum()) if measurable_value.any() else None
    results["opportunity_awaiting_activation"] = _result("opportunity_awaiting_activation", opportunity, f"£{opportunity/1_000_000:.1f}M" if opportunity is not None else "Not measurable yet", opportunity is not None, explanation="Latest unique open vendors with GBP-denominated planned purchase value.")
    risk_mask = open_vendors["vendor_id"].isin(open_critical) & measurable_value
    risk_value = float(values[risk_mask].sum()) if risk_mask.any() else 0.0 if opportunity is not None else None
    risk_display = f"£{risk_value/1_000_000:.1f}M" if risk_value is not None else "Not measurable yet"
    results["opportunity_at_risk"] = _result("opportunity_at_risk", risk_value, risk_display, risk_value is not None, risk_value, opportunity, "Unique open critical vendors; value is never multiplied by findings.")

    measurable_age = open_vendors[open_vendors["age_days"].notna()]
    total_age = float(measurable_age["age_days"].sum())
    vendor_age = float(measurable_age.loc[measurable_age["status"].isin(VENDOR_STATUSES), "age_days"].sum())
    internal_age = float(measurable_age.loc[measurable_age["status"].isin(INTERNAL_STATUSES), "age_days"].sum())
    results["vendor_delay_share"] = _rate("vendor_delay_share", vendor_age, total_age, "Current-state attribution; transition-level attribution becomes available as journey events accumulate.")
    results["internal_delay_share"] = _rate("internal_delay_share", internal_age, total_age, "Current-state attribution; excludes unowned time.")
    owners = open_vendors.get("onboarding_owner", pd.Series("", index=open_vendors.index)).astype(str).str.strip()
    results["unowned_open_rate"] = _rate("unowned_open_rate", int(owners.eq("").sum()), len(open_vendors), "Blank accountable onboarding owner divided by open vendors.")
    revisions = pd.to_numeric(frame.loc[~frame["status"].isin(EXCLUDED_STATUSES), "revision"], errors="coerce").dropna()
    avg_revision = float(revisions.mean()) if len(revisions) else None
    results["average_revision_count"] = _result("average_revision_count", avg_revision, f"{avg_revision:.2f}" if avg_revision is not None else "Not measurable yet", avg_revision is not None)

    expiry = parse_business_dates(frame.get("document_expiry_date", pd.Series("", index=frame.index)))
    days_to_expiry = (expiry - now).dt.total_seconds() / 86400
    eligible_expiry = expiry.notna() & ~frame["status"].isin(EXCLUDED_STATUSES)
    expiring = eligible_expiry & days_to_expiry.between(0, 90, inclusive="both")
    results["documents_expiring_90"] = _rate("documents_expiring_90", int(expiring.sum()), int(eligible_expiry.sum()), "Parseable required documents expiring in 0–90 days.")
    item_counts = pd.to_numeric(open_vendors.get("planned_item_count"), errors="coerce")
    item_mask = open_vendors["vendor_id"].isin(open_critical) & item_counts.notna()
    blocked_items = int(item_counts[item_mask].sum()) if item_mask.any() else 0
    results["items_blocked"] = _result("items_blocked", blocked_items, f"{blocked_items:,}", explanation="Planned downstream items linked to unique current critical vendors.")
    return results


def results_frame(results: dict[str, KPIResult]) -> pd.DataFrame:
    definitions = {metric.key: metric for metric in REGISTRY}
    rows: list[dict[str, Any]] = []
    for key, result in results.items():
        metric = definitions[key]
        rows.append({"KPI": metric.name, "Result": result.display, "Measurable": "Yes" if result.measurable else "No",
                     "Numerator": result.numerator, "Denominator": result.denominator, "Explanation": result.explanation,
                     "Business owner": metric.owner, "Target": metric.target})
    return pd.DataFrame(rows)
