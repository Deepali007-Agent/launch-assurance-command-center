from __future__ import annotations

import html
import os
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import json

from .adapters import (
    get_catalog_actionable_summary,
    get_catalog_rework_metrics,
    get_catalog_agent_assessments,
    get_catalog_bottleneck_summary,
    get_catalog_domain_events,
    get_catalog_domain_snapshot,
    get_catalog_priority_actions,
    get_catalog_workflow_metrics,
)
from .ingestion import read_tabular
from .intelligence import build_intelligence
from .orchestrator import CatalogOperationsOrchestrator
from .persistence.repository import CatalogRepository
from .publishing import FAILED, PUBLISHED, PublicationConfig, RetailIntelligencePublisher
from .services import process_upload


KPI_DEFINITIONS = {
    "Catalog health": "Composite score = 45% average readiness + 35% attribute completeness + 20% critical-blocker-free rate.",
    "Health score": "Composite score = 45% average readiness + 35% attribute completeness + 20% critical-blocker-free rate.",
    "Revenue at risk": "Monthly SKU revenue in INR × severity factor. Critical starts at 35% and Warning at 12%; each additional distinct defect adds 5 points, capped at 55% and 25%.",
    "Expected recovery": "Revenue at Risk multiplied by the governed recovery assumption: 55% for Critical and 70% for Warning findings.",
    "Margin at risk": "Revenue at Risk multiplied by uploaded gross-margin percentage; a governed 35% fallback is used when margin is absent.",
    "Residual revenue risk": "Revenue at Risk remaining after subtracting Expected Recovery; this is the modeled exposure not recovered under current assumptions.",
    "Critical SKUs": "Unique SKUs with at least one Critical finding. A SKU is counted once even when it has several critical defects.",
    "Attribute completeness": "Percentage of seven customer-facing fields populated across the portfolio: title, brand, description, image, colour, size and material.",
    "Clean SKUs": "Unique SKUs with no governed Critical or Warning findings after the latest validation.",
    "Needs action": "Unique SKUs with at least one Critical or Warning finding. Multiple findings on one SKU do not increase this count.",
    "Vendors assessed": "Distinct submitting vendors represented in the current governed portfolio.",
    "High-risk vendors": "Vendors whose governed risk score is at least 60%. The score combines defects, criticality, SLA, returns and revenue exposure.",
    "Vendor exposure": "Total Revenue at Risk in INR allocated to the submitting vendors in the current portfolio.",
    "Top-risk vendor": "Vendor with the highest governed risk priority, then highest risk score and revenue exposure.",
    "Divisions assessed": "Distinct uploaded divisions; Category is used only when Division is not supplied.",
    "Top-risk division": "Division with the highest governed risk priority, then highest risk score and revenue exposure.",
    "Division exposure": "Total Revenue at Risk in INR allocated across merchandising divisions.",
    "CX risk": "Average customer-experience risk from content defects, return-rate risk and rating risk; capped at 100% per SKU.",
    "Actual-input coverage": "Percentage of SKUs whose revenue uses uploaded monthly_sales or units_sold instead of the price × 10 fallback.",
    "Launch pipeline": "Unique current SKUs received and evaluated across the active governed portfolio.",
    "Validation cleared": "Unique SKUs without governed quality exceptions and therefore eligible to enter approval.",
    "Launches at risk": "Unique SKUs requiring content, policy or vendor remediation before approval.",
    "Projected launch delay": "Age in days of the oldest unresolved workflow bottleneck beyond the configured SLA.",
    "Accepted": "Unique SKUs structurally accepted and evaluated in the latest upload.",
    "Rejected": "Structural validation messages that prevented affected rows from entering the workflow.",
    "Run ID": "Immutable audit reference assigned to the latest validation run.",
    "Pass with warnings": "Unique evaluated SKUs with no Critical finding but at least one Warning finding.",
    "Fail": "Unique evaluated SKUs with at least one Critical governed finding.",
    "Pass": "Unique evaluated SKUs with no Critical or Warning governed findings.",
    "Recommendation": "Deterministic agent recommendation based on readiness, blockers and warnings for the selected SKU.",
    "Readiness": "Composite governed readiness score for the selected SKU after the latest validation.",
    "Exceptions": "Total current blocker and warning findings recorded for the selected SKU.",
    "Rework rate": "Percentage of SKUs with at least one recorded material correction or governed version change.",
    "Revisions / SKU": "Average number of immutable recorded item versions per SKU.",
    "Resolution time": "Average elapsed hours between a recorded correction request and its resolved version.",
    "Downstream delay": "Operational hours accumulated after catalog correction before the next downstream stage.",
    "Current status": "Latest governed lifecycle status for the selected SKU.",
    "Revision": "Current immutable version number of the selected SKU.",
    "Journey TAT": "Total recorded elapsed days across the selected SKU's workflow stages.",
    "Stage SLA": "Whether all recorded workflow stages for the selected SKU completed within one day.",
    "Publication status": "Current state of the governed outbound package: Ready to Publish, Published after acknowledgement, or Failed after controlled retries.",
    "Destination": "Whether the parent Retail Intelligence Platform API URL and bearer authentication token are configured.",
    "Publish attempts": "Number of authenticated delivery attempts recorded for this idempotent publication package.",
}


@st.cache_resource
def repository() -> CatalogRepository:
    return CatalogRepository(os.getenv("DATABASE_URL"))


def _label(value: object) -> str:
    raw = str(value or "—")
    labels = {
        "PENDING_HUMAN_APPROVAL": "Awaiting Decision",
        "READY_FOR_APPROVAL": "Awaiting Decision",
        "APPROVED": "Human Approved",
        "ERP_HANDOFF_READY": "Ready for ERP Handoff",
        "ON_HOLD": "On Hold",
        "CREATED_IN_ERP_SIMULATED": "Created (Simulated)",
        "REWORK_REQUIRED": "Correction Required",
        "RETURN_FOR_REWORK": "Return for Correction",
        "ITEM_REWORK_AGENT": "Version Control Agent",
    }
    return labels.get(raw, raw.replace("_", " ").title())


def _metric_card(label: str, value: object, note: str = "", tone: str = "blue") -> None:
    hover = KPI_DEFINITIONS.get(label, note or f"Current value for {label}.")
    st.markdown(
        f"""<div class="metric-card {tone}">
        <div class="metric-label">{html.escape(str(label))} <span class="metric-info">ⓘ<span class="metric-tooltip">{html.escape(hover)}</span></span></div>
        <div class="metric-value">{html.escape(str(value))}</div>
        <div class="metric-note">{html.escape(note) if note else '&nbsp;'}</div></div>""",
        unsafe_allow_html=True,
    )


def _commercial_input_quality(revenue: dict) -> str:
    coverage = float(revenue.get("actual_input_coverage") or 0)
    if coverage >= 99.95:
        return "Complete commercial inputs"
    if coverage >= 80:
        return f"Strong input coverage · {coverage:.1f}%"
    if coverage > 0:
        return f"Partial input coverage · {coverage:.1f}%"
    return "Modeled from fallback inputs"


def _empty(title: str, message: str) -> None:
    st.markdown(
        f'<div class="empty-state"><div class="empty-title">{title}</div><div>{message}</div></div>',
        unsafe_allow_html=True,
    )


def _findings_text(findings: object) -> str:
    if not findings or not isinstance(findings, list):
        return "No issues found"
    return " · ".join(str(f.get("message", "")) for f in findings if isinstance(f, dict)) or "No issues found"


def _actions_text(actions: object) -> str:
    if not actions or not isinstance(actions, list):
        return "No action required"
    return " · ".join(str(a) for a in actions)


def _styled_table(records: list[dict], columns: dict[str, str], height: int | None = None) -> None:
    if not records:
        _empty("Nothing to show yet", "This section will populate when the workflow has relevant records.")
        return
    frame = pd.DataFrame(records)
    selected = [c for c in columns if c in frame.columns]
    frame = frame[selected].rename(columns=columns)
    for column in frame.columns:
        if "Status" in column or "Severity" in column or "Decision" in column:
            frame[column] = frame[column].map(_label)
    options = {"width": "stretch", "hide_index": True}
    if height is not None:
        options["height"] = height
    st.dataframe(frame, **options)


def _chart(chart: alt.Chart, height: int = 280) -> None:
    styled = (
        chart.properties(height=height)
        .configure_view(strokeOpacity=0)
        .configure_axis(
            gridColor="#26314a", domainColor="#46536d", tickColor="#46536d",
            labelColor="#aeb9cb", titleColor="#dce4f2", labelFontSize=12, titleFontSize=12, labelAngle=0, labelLimit=180,
        )
        .configure_legend(labelColor="#aeb9cb", titleColor="#dce4f2")
    )
    st.altair_chart(styled, width="stretch")


def _risk_score_chart(records: list[dict], group_field: str, group_title: str) -> None:
    """Show comparable governed risk scores without replacing the detailed table."""
    if not records:
        return
    frame = pd.DataFrame(records).sort_values(["risk_score", "revenue_at_risk"], ascending=False).head(8)
    frame["Label"] = frame["risk_score"].map(lambda value: f"{value:.1f}%")
    bars = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=6)
        .encode(
            y=alt.Y("risk_score:Q", title="Governed risk score (%)", scale=alt.Scale(domain=[0, 100])),
            x=alt.X(f"{group_field}:N", title=None, sort="-y"),
            color=alt.Color(
                "risk_level:N", title="Risk tier",
                scale=alt.Scale(domain=["High", "Medium", "Low"], range=["#ef6b73", "#f1bd62", "#7cc9ad"]),
            ),
            tooltip=[
                alt.Tooltip(f"{group_field}:N", title=group_title),
                alt.Tooltip("risk_score:Q", title="Risk score", format=".1f"),
                alt.Tooltip("affected_skus:Q", title="Affected SKUs", format=",.0f"),
                alt.Tooltip("revenue_at_risk:Q", title="Revenue at risk (INR)", format=",.0f"),
            ],
        )
    )
    labels = alt.Chart(frame).mark_text(dy=-9, color="#eef2ff", fontWeight="bold").encode(
        y="risk_score:Q", x=alt.X(f"{group_field}:N", sort="-y"), text="Label:N",
    )
    _chart(bars + labels, 270)


def _financial_and_cx_charts(sku_rows: list[dict]) -> None:
    if not sku_rows:
        return
    frame = pd.DataFrame(sku_rows)
    exposure = frame.groupby("severity", as_index=False)["revenue_at_risk"].sum()
    exposure = exposure[exposure["revenue_at_risk"] > 0]
    exposure["share_pct"] = exposure["revenue_at_risk"] / exposure["revenue_at_risk"].sum() * 100
    exposure["Label"] = exposure["share_pct"].map(lambda value: f"{value:.1f}%")
    cx = frame.groupby("division", as_index=False).agg(
        cx_risk_score=("cx_risk_score", "mean"), affected_skus=("severity", lambda values: int((values != "NONE").sum()))
    ).sort_values("cx_risk_score", ascending=False)
    left, right = st.columns(2)
    with left:
        st.markdown("### Revenue exposure by severity")
        bars = alt.Chart(exposure).mark_bar(cornerRadiusEnd=6).encode(
            y=alt.Y("revenue_at_risk:Q", title="Revenue at risk (INR)"),
            x=alt.X("severity:N", title=None, sort=["CRITICAL", "WARNING"]),
            color=alt.Color(
                "severity:N", title="Severity",
                scale=alt.Scale(domain=["CRITICAL", "WARNING"], range=["#ef6b73", "#f1bd62"]),
            ),
            tooltip=[
                alt.Tooltip("severity:N", title="Severity"),
                alt.Tooltip("revenue_at_risk:Q", title="Revenue at risk (INR)", format=",.0f"),
                alt.Tooltip("share_pct:Q", title="% of exposure", format=".1f"),
            ],
        )
        labels = alt.Chart(exposure).mark_text(dy=-9, color="#eef2ff", fontWeight="bold").encode(
            y="revenue_at_risk:Q", x=alt.X("severity:N", sort=["CRITICAL", "WARNING"]), text="Label:N",
        )
        _chart(bars + labels, 245)
    with right:
        st.markdown("### Customer risk by division")
        cx["Label"] = cx["cx_risk_score"].map(lambda value: f"{value:.1f}%")
        bars = alt.Chart(cx).mark_bar(cornerRadiusEnd=6, color="#7f8fe8").encode(
            y=alt.Y("cx_risk_score:Q", title="Average CX risk score", scale=alt.Scale(domain=[0, 100])),
            x=alt.X("division:N", title=None, sort="-y"),
            tooltip=[
                alt.Tooltip("division:N", title="Division"),
                alt.Tooltip("cx_risk_score:Q", title="Average CX risk", format=".1f"),
                alt.Tooltip("affected_skus:Q", title="Affected SKUs", format=",.0f"),
            ],
        )
        labels = alt.Chart(cx).mark_text(dy=-9, color="#eef2ff", fontWeight="bold").encode(
            y="cx_risk_score:Q", x=alt.X("division:N", sort="-y"), text="Label:N",
        )
        _chart(bars + labels, 245)


def _recovery_priority_summary(sku_rows: list[dict]) -> list[dict]:
    """Consolidate SKU-level recovery detail into leadership-sized division actions."""
    action_map = {
        "image_url": "Correct imagery and revalidate",
        "description": "Improve descriptions and revalidate",
        "vendor_approval": "Resolve vendor approval",
        "vendor_id": "Resolve vendor approval",
        "size": "Complete size attributes",
        "material": "Complete material attributes",
        "brand": "Complete brand information",
    }
    affected = [row for row in sku_rows if row["severity"] != "NONE"]
    groups: dict[str, list[dict]] = {}
    for row in affected:
        groups.setdefault(str(row["division"]), []).append(row)
    result = []
    for division, rows in groups.items():
        field_counts: dict[str, int] = {}
        for row in rows:
            for field in row.get("affected_fields") or []:
                field_counts[field] = field_counts.get(field, 0) + 1
        driver = max(field_counts, key=field_counts.get) if field_counts else "general"
        result.append({
            "division": division,
            "affected_skus": len({row["sku"] for row in rows}),
            "critical_skus": sum(row["severity"] == "CRITICAL" for row in rows),
            "top_driver": driver.replace("_", " ").title(),
            "revenue_at_risk": round(sum(row["revenue_at_risk"] for row in rows), 2),
            "expected_recovery": round(sum(row["expected_recovery"] for row in rows), 2),
            "margin_at_risk": round(sum(row["margin_at_risk"] for row in rows), 2),
            "residual_revenue_risk": round(sum(row["residual_revenue_risk"] for row in rows), 2),
            "cx_risk_score": round(sum(row["cx_risk_score"] for row in rows) / len(rows), 1),
            "owner": "Division / Merchandising Lead",
            "action": action_map.get(driver, "Correct catalog defects and revalidate"),
        })
    return sorted(result, key=lambda row: (-row["expected_recovery"], -row["critical_skus"]))


def _root_cause_chart(records: list[dict]) -> None:
    if not records:
        return
    frame = pd.DataFrame(records).head(8).copy()
    frame["Label"] = frame["composition_pct"].map(lambda value: f"{value:.1f}%")
    bars = alt.Chart(frame).mark_bar(cornerRadiusEnd=6).encode(
        y=alt.Y("composition_pct:Q", title="Unique affected SKUs (% of portfolio)", scale=alt.Scale(domain=[0, 100])),
        x=alt.X("actionable:N", title=None, sort="-y"),
        color=alt.Color(
            "severity:N", title="Highest severity",
            scale=alt.Scale(domain=["Critical", "Warning"], range=["#ef6b73", "#f1bd62"]),
        ),
        tooltip=[
            alt.Tooltip("actionable:N", title="Root cause"),
            alt.Tooltip("affected_skus:Q", title="Unique affected SKUs", format=",.0f"),
            alt.Tooltip("composition_pct:Q", title="% of portfolio", format=".1f"),
            alt.Tooltip("severity:N", title="Highest severity"),
        ],
    )
    labels = alt.Chart(frame).mark_text(dy=-9, color="#eef2ff", fontWeight="bold").encode(
        y="composition_pct:Q", x=alt.X("actionable:N", sort="-y"), text="Label:N",
    )
    _chart(bars + labels, 270)


def _leadership_action_summary(vendors: list[dict], divisions: list[dict]) -> list[dict]:
    rows = []
    for scope_type, records, key, owner in (
        ("Vendor", vendors[:3], "vendor", "Vendor Operations"),
        ("Division", divisions[:2], "division", "Division / Merchandising Lead"),
    ):
        for record in records:
            rows.append({
                "priority": record["priority"], "scope_type": scope_type, "scope": record[key],
                "root_cause": record["root_cause"], "affected_skus": record["affected_skus"],
                "revenue_at_risk": record["revenue_at_risk"], "expected_recovery": record["expected_recovery"],
                "owner": owner, "action": record["recommended_action"],
            })
    return sorted(rows, key=lambda row: (row["priority"], -row["revenue_at_risk"]))


def _brand_quality_intelligence(current_items: list[dict], latest_by_agent: dict) -> None:
    """Render a leadership-ready brand view from the latest quality and policy findings."""
    item_lookup = {item["sku"]: item for item in current_items}
    brand_options = sorted({item.get("brand") or "Unspecified" for item in current_items})
    vendor_options = sorted({item.get("vendor_name") or item.get("vendor_id") or "Unspecified" for item in current_items})
    filter_left, filter_right = st.columns(2)
    with filter_left:
        selected_brands = st.multiselect("Brand", brand_options, placeholder="All brands", key="quality_brand_filter")
    with filter_right:
        selected_vendors = st.multiselect("Vendor", vendor_options, placeholder="All vendors", key="quality_vendor_filter")
    filtered_items = [
        item for item in current_items
        if (not selected_brands or (item.get("brand") or "Unspecified") in selected_brands)
        and (not selected_vendors or (item.get("vendor_name") or item.get("vendor_id") or "Unspecified") in selected_vendors)
    ]
    filtered_skus = {item["sku"] for item in filtered_items}
    issue_names = {
        "image_url": "Product image", "description": "Description", "brand": "Brand",
        "colour": "Colour", "size": "Size", "material": "Material",
        "vendor_id": "Vendor approval", "vendor_approved": "Vendor approval", "gtin": "GTIN",
        "price": "Price", "product_name": "Product title",
    }
    action_names = {
        "Product image": "Add or correct product imagery", "Description": "Improve customer-facing descriptions",
        "Brand": "Complete brand information", "Colour": "Complete colour attributes",
        "Size": "Complete size attributes", "Material": "Complete material attributes",
        "Vendor approval": "Resolve vendor authorization", "GTIN": "Correct product identifiers",
        "Price": "Correct commercial data", "Product title": "Improve product titles",
    }
    sku_findings: dict[str, list[dict]] = {}
    for (sku, agent), assessment in latest_by_agent.items():
        if sku in filtered_skus and agent in {"CATALOG_QUALITY_AGENT", "POLICY_VALIDATION_AGENT"}:
            sku_findings.setdefault(sku, []).extend(assessment.get("findings", []))

    brand_rows, issue_rows, queue_rows = [], [], []
    for brand in sorted({item.get("brand") or "Unspecified" for item in filtered_items}):
        brand_items = [item for item in filtered_items if (item.get("brand") or "Unspecified") == brand]
        brand_skus = {item["sku"] for item in brand_items}
        affected = {sku for sku in brand_skus if sku_findings.get(sku)}
        critical = {sku for sku in affected if any(f.get("severity") == "CRITICAL" for f in sku_findings[sku])}
        warnings = affected - critical
        if not affected:
            continue
        submitted = len(brand_skus)
        affected_pct = len(affected) / submitted * 100 if submitted else 0
        for status, count in (("Pass with warnings", len(warnings)), ("Fail", len(critical))):
            brand_rows.append({"Brand": brand, "Status": status, "SKUs": count, "Total": len(affected),
                               "Rate": affected_pct, "Label": f"{len(affected)} · {affected_pct:.1f}%"})
        issue_counts: dict[str, set[str]] = {}
        for sku in affected:
            for finding in sku_findings[sku]:
                issue = issue_names.get(finding.get("field"), _label(finding.get("field")))
                issue_counts.setdefault(issue, set()).add(sku)
        for issue, skus in issue_counts.items():
            issue_rows.append({"Brand": brand, "Issue": issue, "SKUs": len(skus), "Rate": len(skus) / submitted * 100,
                               "Label": f"{len(skus)} · {len(skus) / submitted * 100:.1f}%"})
        top_issue = max(issue_counts, key=lambda name: len(issue_counts[name]))
        timestamps = pd.to_datetime([item.get("submitted_at") for item in brand_items if item.get("submitted_at")], utc=True, errors="coerce")
        oldest_age = max(((pd.Timestamp.now(tz="UTC") - value).total_seconds() / 86400 for value in timestamps if not pd.isna(value)), default=0.0)
        vendors = sorted({f'{item.get("vendor_name") or "Unknown"} ({item.get("vendor_id") or "—"})' for item in brand_items})
        queue_rows.append({
            "brand": brand, "vendor": "; ".join(vendors), "submitted_skus": submitted,
            "warnings": len(warnings), "failed": len(critical), "affected_skus": len(affected),
            "failure_rate": round(affected_pct, 1), "critical_skus": len(critical), "top_issue": top_issue,
            "delay_days": round(max(0.0, oldest_age - 1.0), 2),
            "required_action": action_names.get(top_issue, "Review and correct catalog attributes"),
        })

    if not brand_rows:
        _empty("No brand-level quality exceptions", "The selected brands and vendors have no quality or policy findings.")
        return
    detail_rows = []
    for sku, findings in sku_findings.items():
        item = item_lookup.get(sku, {})
        for finding in findings:
            issue = issue_names.get(finding.get("field"), _label(finding.get("field")))
            detail_rows.append({
                "sku": sku, "product": item.get("product_name", ""), "brand": item.get("brand") or "Unspecified",
                "vendor_id": item.get("vendor_id", ""), "vendor": item.get("vendor_name", ""),
                "category": item.get("category", ""), "severity": _label(finding.get("severity")),
                "issue": issue, "finding": finding.get("message", ""),
                "required_action": action_names.get(issue, "Review and correct catalog attributes"),
            })
    detail_frame = pd.DataFrame(detail_rows)
    st.download_button(
        "Download detailed information-quality findings",
        data=detail_frame.to_csv(index=False).encode("utf-8"),
        file_name="catalogiq_information_quality_findings.csv", mime="text/csv", width="stretch",
    )


def _workflow_strip(items: list[dict], quality_exceptions: int, approval_eligible: int) -> None:
    statuses = [i.get("lifecycle_status", "") for i in items]
    stages = [
        ("1", "Intake", len(items), "Items received and validated"),
        ("2", "Quality review", quality_exceptions, "SKUs needing content or policy action"),
        ("3", "Approval queue", approval_eligible, "Quality-cleared SKUs awaiting approval"),
        ("4", "Correction required", statuses.count("REWORK_REQUIRED"), "Returned for a pre-live correction"),
        ("5", "ERP-ready", statuses.count("ERP_HANDOFF_READY"), "Approved for simulated handoff"),
    ]
    html = '<div class="workflow-strip">'
    for number, name, count, note in stages:
        html += (
            f'<div class="workflow-stage"><span class="stage-number">{number}</span>'
            f'<div><div class="stage-name">{name}</div><div class="stage-count">{count}</div>'
            f'<div class="stage-note">{note}</div></div></div>'
        )
    st.markdown(html + "</div>", unsafe_allow_html=True)


def _executive_brief(snapshot: dict, workflow: dict, approval_eligible: int, critical_skus: int = 0) -> None:
    if snapshot["evaluated_skus"] == 0:
        headline = "Upload a supplier catalog to establish the first governed baseline."
        detail = "Catalog Operations will validate intake, score publication readiness, and build a human approval queue."
        tone = "blue"
    elif critical_skus:
        headline = f'{critical_skus} SKUs are blocked by critical quality issues.'
        detail = "Prioritize the affected brands and accountable teams before requesting human approval."
        tone = "red"
    elif approval_eligible:
        headline = f'{approval_eligible} quality-cleared SKUs are in the approval queue.'
        detail = f'{workflow["approval_sla_breaches"]} items exceed the {workflow["approval_sla_days"]:.0f}-day approval SLA. Clear aged items first, then prepare the simulated ERP handoff.'
        tone = "amber"
    else:
        headline = "The catalog workflow is operating without critical blockers."
        detail = f'Intake SLA compliance is {workflow["intake_sla_compliance_pct"]:.0f}% with {snapshot["ready_skus"]} SKUs currently ERP-ready.'
        tone = "green"
    st.markdown(
        f'<div class="executive-brief {tone}"><div class="brief-kicker">Executive brief</div>'
        f'<div class="brief-headline">{headline}</div><div class="brief-detail">{detail}</div></div>',
        unsafe_allow_html=True,
    )


def _inject_theme() -> None:
    st.markdown(
        """<style>
        .stApp {background: #0b1020; color: #e8edf7;}
        .block-container {max-width: 1440px; padding-top: 1.6rem; padding-bottom: 3rem;}
        h1 {font-size: 2.25rem !important; letter-spacing: -0.035em; margin-bottom: .2rem !important;}
        h2, h3 {letter-spacing: -0.02em;}
        [data-testid="stCaptionContainer"] {color: #9aa8be;}
        [data-testid="stTabs"] [data-baseweb="tab-list"] {gap: .25rem; background: #11182a; padding: .35rem; border-radius: 12px;}
        [data-testid="stTabs"] [data-baseweb="tab"] {height: 42px; border-radius: 9px; padding: 0 .9rem; color: #aeb9cb;}
        [data-testid="stTabs"] [aria-selected="true"] {background: #243054; color: #fff !important;}
        [data-testid="stTabs"] [data-baseweb="tab-highlight"] {display:none;}
        .metric-card {min-height: 128px; border: 1px solid #26314a; background: linear-gradient(145deg,#141c30,#101728); border-radius: 14px; padding: 18px 20px;}
        .metric-card.blue {border-top: 3px solid #6d8cff;} .metric-card.green {border-top: 3px solid #43c59e;}
        .metric-card.amber {border-top: 3px solid #f4b860;} .metric-card.red {border-top: 3px solid #ef6a6a;}
        .metric-label {font-size: .78rem; color: #9aa8be; text-transform: uppercase; letter-spacing: .08em; font-weight: 700;}
        .metric-info {position:relative; display:inline-block; cursor:help; color:#aebcff; text-transform:none; letter-spacing:0;}
        .metric-tooltip {visibility:hidden; opacity:0; position:absolute; z-index:9999; left:0; top:1.5rem; width:320px;
            padding:10px 12px; border:1px solid #46577b; border-radius:9px; background:#070c18; color:#e8edf7;
            font-size:.78rem; font-weight:500; line-height:1.45; letter-spacing:0; text-transform:none; box-shadow:0 8px 28px rgba(0,0,0,.45);
            transition:opacity .12s ease; pointer-events:none; white-space:normal;}
        .metric-info:hover .metric-tooltip, .metric-info:focus .metric-tooltip {visibility:visible; opacity:1;}
        .metric-value {font-size: 2rem; font-weight: 750; margin: .4rem 0 .2rem; letter-spacing: -.04em;}
        .metric-note {font-size: .78rem; color: #8290a7;}
        .section-kicker {color:#7f98ff; font-weight:700; font-size:.76rem; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.3rem;}
        .hero-panel {border:1px solid #293653; background:linear-gradient(135deg,#17213a,#10182a); border-radius:16px; padding:22px 24px; margin:.75rem 0 1.2rem;}
        .hero-title {font-size:1.2rem;font-weight:750;margin-bottom:.35rem}.hero-copy{color:#a8b4c8;max-width:850px;line-height:1.55}
        .status-pill {display:inline-flex; padding:.38rem .68rem; border-radius:999px; background:#233154; color:#b9c8ff; font-size:.78rem; font-weight:700; letter-spacing:.03em;}
        .empty-state {border:1px dashed #33415f; background:#11182a; border-radius:12px; padding:20px; color:#8695ad; margin:.5rem 0 1rem;}
        .empty-title {font-weight:700;color:#d6deec;margin-bottom:.25rem;}
        .detail-card {border:1px solid #26314a;background:#11182a;border-radius:14px;padding:18px 20px;margin:.35rem 0;}
        .detail-row {display:flex;justify-content:space-between;gap:1rem;padding:.55rem 0;border-bottom:1px solid #202a40;}
        .detail-row:last-child{border-bottom:0}.detail-key{color:#8f9db3}.detail-value{font-weight:650;text-align:right}
        .workflow-strip {display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:1rem 0 1.4rem;}
        .workflow-stage {display:flex;gap:12px;align-items:flex-start;border:1px solid #26314a;background:#11182a;border-radius:12px;padding:14px;min-height:100px;}
        .stage-number {display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:#26365f;color:#c8d3ff;font-weight:800;font-size:.75rem;flex:0 0 auto;}
        .stage-name {font-size:.8rem;color:#aeb9cb;font-weight:700}.stage-count{font-size:1.45rem;font-weight:800;line-height:1.2;margin:.2rem 0}.stage-note{font-size:.7rem;color:#78869d;line-height:1.3}
        .executive-brief {border:1px solid #2b3855;border-left:4px solid #6d8cff;background:#11182a;border-radius:12px;padding:18px 20px;margin:.4rem 0 1.25rem;}
        .executive-brief.green{border-left-color:#43c59e}.executive-brief.amber{border-left-color:#f4b860}.executive-brief.red{border-left-color:#ef6a6a}
        .brief-kicker{font-size:.72rem;text-transform:uppercase;letter-spacing:.1em;color:#8290a7;font-weight:750}.brief-headline{font-size:1.15rem;font-weight:750;margin:.35rem 0}.brief-detail{font-size:.88rem;color:#a8b4c8;line-height:1.5}
        .next-step {border:1px solid #314369;background:#14203a;border-radius:12px;padding:15px 18px;margin:1rem 0;color:#b9c8df}.next-step b{color:#fff}
        @media (max-width: 900px) {.workflow-strip{grid-template-columns:1fr 1fr}.workflow-stage{min-height:90px}}
        div.stButton > button[kind="primary"] {background:#657cf4;border-color:#657cf4;color:white;border-radius:10px;font-weight:700;}
        div.stButton > button {border-radius:10px;border-color:#35415a;min-height:44px;}
        [data-testid="stFileUploader"] {border:1px dashed #405073;border-radius:12px;padding:.3rem;background:#10182a;}
        [data-testid="stDataFrame"] {border:1px solid #26314a;border-radius:12px;overflow:hidden;}
        [data-testid="stAlert"] {border-radius:12px;}
        </style>""",
        unsafe_allow_html=True,
    )


def _money(value: object) -> str:
    return f"INR {float(value or 0):,.0f}"


def _with_inr(records: list[dict], *fields: str) -> list[dict]:
    formatted = []
    for record in records:
        row = dict(record)
        for field in fields:
            if field in row:
                row[field] = _money(row[field])
        formatted.append(row)
    return formatted


def _leadership_workspace(repo: CatalogRepository, connected=False) -> None:
    if not connected:
        with st.expander("Upload or replace data", expanded=True):
            st.caption("Upload a CSV or Excel catalog here. The same governed intake and revalidation workflow is used by the operational workspace.")
            uploaded = st.file_uploader("Catalog dataset", type=["csv", "xlsx"], key="leadership_dataset_upload")
            replace_catalog = st.checkbox("Replace the current portfolio", value=True, key="leadership_replace_catalog")
            if st.button("Validate and refresh intelligence", type="primary", width="stretch", key="leadership_validate"):
                if uploaded is None:
                    st.warning("Choose a CSV or Excel file first.")
                else:
                    try:
                        frame = read_tabular(uploaded, uploaded.name)
                        result = process_upload(frame, uploaded.name, repo, replace_catalog=replace_catalog)
                        if result.ingestion.errors:
                            st.error(f"The file contains {len(result.ingestion.errors)} structural validation messages. The active portfolio was not replaced.")
                            _styled_table(
                                [{"field": e.field, "code": e.code, "message": e.message} for e in result.ingestion.errors],
                                {"field":"Field", "code":"Issue", "message":"How to fix"},
                            )
                        else:
                            st.session_state.pop("approval_sku", None)
                            st.session_state.pop("history_sku", None)
                            st.success(f"Validated {len(result.ingestion.items)} unique SKUs. Refreshing leadership intelligence.")
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Dataset could not be processed: {exc}")
    intelligence = build_intelligence(repo)
    catalog = intelligence["catalog"]
    revenue = intelligence["revenue"]
    customer = intelligence["customer"]
    executive = intelligence["executive"]
    vendors = intelligence["vendor"]
    divisions = intelligence["division"]
    tabs = st.tabs([
        "Executive Summary", "Catalog Health", "Vendor Intelligence",
        "Division Performance", "Revenue & Customer Impact",
    ])

    with tabs[0]:
        st.subheader("Executive Summary")
        orchestration = intelligence["orchestration"]
        sync = orchestration["synchronization"]
        if sync["status"] == "VERIFIED":
            st.success(
                f"Executive orchestration verified · {sync['checked_skus']} current SKUs · "
                f"{len(orchestration['domain_contracts'])} synchronized domain contracts · "
                f"Policy {orchestration['policy_version']}"
            )
        else:
            st.error(
                f"Executive orchestration {sync['status'].lower()} · "
                f"{len(sync['missing_inputs'])} missing or stale inputs. Revalidate the current dataset."
            )
        with st.expander("How Catalog checks support this decision"):
            st.write("This is the audit trail behind Catalog’s recommendation: which specialist supplied each result, which rule version it used, and which validation run it belongs to.")
            st.caption("Use it to confirm the recommendation uses assessments for the current SKU versions, rather than older results. These are Catalog’s internal checks; this panel does not prove that Vendor and PO agents are connected or that a release is approved.")
            evidence = [{
                "Domain": name.replace("_", " ").title(),
                "Calculation authority": contract["authority"].replace("_", " ").title(),
                "Confidence": contract["confidence"],
                "Policy version": contract["policy_version"],
                "Run IDs": ", ".join(contract["run_ids"]) or "Legacy/unavailable",
            } for name, contract in orchestration["domain_contracts"].items()]
            _styled_table(evidence, {
                "Domain":"Domain", "Calculation authority":"Calculation authority",
                "Confidence":"Confidence", "Policy version":"Policy version", "Run IDs":"Source run IDs",
            })
            st.caption(
                f"Generated {orchestration['generated_at']} · Contract {orchestration['contract_version']} · "
                f"Portfolio mode: {sync['portfolio_mode'].replace('_', ' ').title()}"
            )
        decision = executive["decision"]
        if decision == "NOT AVAILABLE":
            st.error(
                "Decision: NOT AVAILABLE — executive intelligence is blocked because one or more current SKU versions "
                "do not have synchronized quality assessments and a domain decision. Revalidate the current dataset."
            )
        elif decision == "HOLD":
            st.error(
                f"Decision: {decision} — remediate {catalog['critical_skus']} critical SKUs before release. "
                f"Immediate focus: {executive['top_risk_vendor']} and {executive['top_risk_division']}; "
                f"modeled exposure is {_money(revenue['revenue_at_risk'])}."
            )
        elif decision == "PARTIAL HOLD":
            st.warning(
                f"Decision: PARTIAL HOLD — quarantine {catalog['critical_skus']} critical SKUs and allow clean SKUs to continue. "
                f"Scope: {catalog['decision_scope']}; modeled exposure is {_money(revenue['revenue_at_risk'])}."
            )
        elif decision == "CONDITIONAL GO":
            st.warning(
                f"Catalog review required — review {catalog['warning_skus']} warning-only SKUs. "
                f"Expected recovery is {_money(revenue['expected_recovery'])}."
            )
        else:
            st.success("Catalog checks clear — submit this evidence to the retail cycle for review.")
        row = st.columns(4)
        with row[0]: _metric_card("Catalog status", decision.replace("_", " ").title(), f'{catalog["total_skus"]} SKUs evaluated', "red" if catalog["critical_skus"] else "amber" if catalog["warning_skus"] else "green")
        with row[1]: _metric_card("Revenue at risk", _money(revenue["revenue_at_risk"]), _commercial_input_quality(revenue), "red" if revenue["revenue_at_risk"] else "green")
        with row[2]: _metric_card("Expected recovery", _money(revenue["expected_recovery"]), f'{revenue["recovery_rate"]:.1f}% of exposure', "green")
        with row[3]: _metric_card("Critical SKUs", catalog["critical_skus"], f'{catalog["warning_skus"]} warning-only SKUs', "red" if catalog["critical_skus"] else "amber")
        st.markdown("### Priority view")
        priority_view = st.radio(
            "View priorities by", ["Vendor", "Division", "Root cause"], horizontal=True,
            key="executive_priority_view", label_visibility="collapsed",
        )
        if priority_view == "Vendor":
            _risk_score_chart(vendors[:5], "vendor", "Vendor")
        elif priority_view == "Division":
            _risk_score_chart(divisions[:5], "division", "Division")
        else:
            _root_cause_chart(get_catalog_actionable_summary(repo))
        st.markdown("### Leadership action plan")
        leadership_rows = executive.get("governed_actions", [])
        _styled_table(_with_inr(leadership_rows, "revenue_at_risk", "recovery_target"), {
            "priority":"Priority", "scope":"Risk area", "status":"Status", "owner":"Accountable team",
            "due_at":"Due date", "revenue_at_risk":"Exposure (INR)",
            "recovery_target":"Recovery target (INR)", "action":"Immediate action",
        })
        st.caption(
            "Open means the risk remains present in the latest validated dataset. Actions close automatically after "
            "successful revalidation. Accountable team identifies the responsible function, not a named individual. "
            "Vendor and Division scopes overlap and are not additive."
        )
        if connected:
            st.caption('Current item results are already linked to this shared batch in Retail Intelligence. Use Actions & Approvals for human review and the separate simulated ERP handoff.')
        else:
            st.markdown("### Publish to Retail Intelligence")
            publisher = RetailIntelligencePublisher(repo, PublicationConfig.from_env())
            publication = publisher.prepare(intelligence)
            publish_columns = st.columns(3)
            status_label = publication["status"].replace("_", " ").title()
            with publish_columns[0]:
                _metric_card("Publication status", status_label,
                             "Awaiting explicit publication" if publication["status"] != PUBLISHED else "Acknowledged by parent platform",
                             "green" if publication["status"] == PUBLISHED else "red" if publication["status"] == FAILED else "amber")
            with publish_columns[1]:
                _metric_card("Destination", "Configured" if publisher.config.is_configured else "Not configured",
                             "Retail Intelligence API" if publisher.config.is_configured else "Set API URL and token",
                             "green" if publisher.config.is_configured else "amber")
            with publish_columns[2]:
                _metric_card("Publish attempts", publication["attempt_count"],
                             f"Package {publication['publication_id']}", "green" if publication["status"] == PUBLISHED else "blue")
            publish_disabled = (
                not publisher.config.is_configured or publication["status"] == PUBLISHED
                or orchestration["synchronization"]["status"] != "VERIFIED"
            )
            publish_label = "Retry publish to Retail Intelligence" if publication["status"] == FAILED else "Publish to Retail Intelligence"
            if st.button(publish_label, key=f"publish_{publication['publication_id']}",
                         disabled=publish_disabled, type="primary", width="stretch"):
                try:
                    published = publisher.publish(publication["publication_id"])
                    if published["status"] == PUBLISHED:
                        st.success(f"Published and acknowledged · {published['publication_id']}")
                    else:
                        st.error(f"Publication failed after {published['attempt_count']} attempts. Retry is available.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Publication could not start: {exc}")
            st.download_button(
                "Download parent-platform publication package",
                json.dumps(publication["payload"], indent=2).encode("utf-8"),
                f"{publication['publication_id'].lower()}-retail-intelligence.json",
                "application/json", width="stretch",
            )
            with st.expander("Publication configuration and acknowledgement"):
                st.markdown(
                    f"- **Schema:** `{publication['payload']['schema']}`\n"
                    f"- **Orchestration run:** `{publication['orchestration_run_id']}`\n"
                    f"- **Dataset runs:** `{', '.join(publication['dataset_run_ids'])}`\n"
                    f"- **Endpoint:** `{publisher.config.endpoint or 'Not configured'}`\n"
                    f"- **Authentication:** `Bearer token — {'configured' if publisher.config.token else 'not configured'}`\n"
                    f"- **Retry policy:** `{publisher.config.max_attempts} attempts with controlled backoff`\n"
                    f"- **Acknowledgement:** `{json.dumps(publication.get('acknowledgement')) if publication.get('acknowledgement') else 'Not received'}`\n"
                    f"- **Last error:** `{publication.get('last_error') or 'None'}`"
                )
        with st.expander("How these numbers are calculated"):
            st.markdown(
                f"**Policy version:** `{intelligence['policy']['version']}`\n\n"
                f"- **Catalog health:** {KPI_DEFINITIONS['Catalog health']}\n"
                f"- **Revenue at Risk:** {KPI_DEFINITIONS['Revenue at risk']}\n"
                f"- **Expected recovery:** {KPI_DEFINITIONS['Expected recovery']}\n"
                f"- **Release decision:** Portfolio HOLD at {intelligence['policy']['portfolio_hold_critical_rate_pct']:.0f}% critical SKUs or "
                f"{intelligence['policy']['portfolio_hold_critical_exposure_pct']:.0f}% critical exposure; otherwise only affected scopes are held.\n"
                "- **Vendor and Division risk:** 30% affected-SKU rate + 25% critical-SKU rate + 20% SLA shortfall + 10% return-rate risk + 15% exposure concentration.\n"
                "- **Root causes:** one SKU is counted once per affected attribute; root-cause rows therefore do not sum to the portfolio total."
                f"\n- **Orchestration status:** {executive['synchronization']['status']} across "
                f"{executive['synchronization']['checked_skus']} current SKUs; source run IDs: "
                f"{', '.join(executive['synchronization']['run_ids']) or 'legacy/unavailable'}."
            )

    with tabs[1]:
        st.subheader("Catalog Health")
        row = st.columns(4)
        with row[0]: _metric_card("Health score", f'{catalog["health_score"]:.1f}%', "45% readiness · 35% completeness · 20% blocker-free", "green" if catalog["health_score"] >= 90 else "amber")
        with row[1]: _metric_card("Attribute completeness", f'{catalog["attribute_completeness"]:.1f}%', "Seven customer-facing fields")
        with row[2]: _metric_card("Clean SKUs", catalog["clean_skus"], f'of {catalog["total_skus"]} evaluated', "green")
        with row[3]: _metric_card("Needs action", catalog["critical_skus"] + catalog["warning_skus"], "Unique affected SKUs", "red" if catalog["critical_skus"] else "amber")
        st.markdown("### Top error drivers")
        _styled_table(get_catalog_actionable_summary(repo), {
            "actionable":"Attribute", "affected_skus":"Affected SKUs", "composition_pct":"% of portfolio",
            "severity":"Highest severity", "recommended_action":"Required action",
        })
        st.markdown("### Catalog disposition")
        disposition = [
            {"status":"Ready for approval", "skus":catalog["clean_skus"], "definition":"100% complete, no governed quality or policy findings"},
            {"status":"Review warnings", "skus":catalog["warning_skus"], "definition":"No critical blocker; warning acceptance or correction required"},
            {"status":"Correction required", "skus":catalog["critical_skus"], "definition":"Critical blocker prevents approval and downstream creation"},
        ]
        _styled_table(disposition, {"status":"Disposition", "skus":"SKUs", "definition":"Meaning"})
        ready_rows = [row for row in intelligence["sku"] if row["severity"] == "NONE" and row["readiness"] >= 100]
        action_rows = [row for row in intelligence["sku"] if row["severity"] != "NONE"]
        downloads = st.columns(2)
        downloads[0].download_button(
            f"Download {len(ready_rows)} ready-for-approval SKUs",
            pd.DataFrame(ready_rows).to_csv(index=False).encode("utf-8"),
            "catalogiq_ready_for_approval.csv", "text/csv", width="stretch",
        )
        downloads[1].download_button(
            f"Download {len(action_rows)} SKUs requiring review",
            pd.DataFrame(action_rows).to_csv(index=False).encode("utf-8"),
            "catalogiq_skus_requiring_review.csv", "text/csv", width="stretch",
        )

    with tabs[2]:
        st.subheader("Vendor Intelligence")
        st.caption("Vendor approval and risk originate in Vendor Intelligence; Catalog IQ consumes those signals and adds catalog-linked exposure.")
        high = sum(v["risk_level"] == "High" for v in vendors)
        row = st.columns(4)
        with row[0]: _metric_card("Vendors assessed", len(vendors), "Connected submitting partners")
        with row[1]: _metric_card("High-risk vendors", high, "Immediate leadership attention", "red" if high else "green")
        with row[2]: _metric_card("Vendor exposure", _money(sum(v["revenue_at_risk"] for v in vendors)), "Catalog-linked")
        with row[3]: _metric_card("Top-risk vendor", executive["top_risk_vendor"], "Ranked by risk and exposure", "amber")
        st.markdown("### Vendor risk comparison")
        _risk_score_chart(vendors, "vendor", "Vendor")
        _styled_table(_with_inr(vendors, "revenue_at_risk", "expected_recovery"), {
            "vendor":"Vendor", "submitted_skus":"Submitted", "affected_skus":"Affected",
            "critical_skus":"Critical", "risk_score":"Risk score", "risk_level":"Risk tier",
            "sla_compliance":"SLA (%)", "average_return_rate":"Return rate (%)",
            "root_cause":"Root cause", "revenue_at_risk":"Exposure (INR)", "expected_recovery":"Recovery (INR)",
            "priority":"Priority", "owner":"Owner", "recommended_action":"Leadership action",
        }, 460)
        st.caption("Vendor risk score = 30% affected-SKU rate + 25% critical-SKU rate + 20% SLA shortfall + 10% return-rate risk + 15% exposure concentration.")
        st.info("Vendor onboarding remains the source of approval, compliance and SLA data. Item onboarding stays in Catalog Operations and is automatically blocked when vendor approval is absent.")

    with tabs[3]:
        st.subheader("Division Performance")
        row = st.columns(3)
        with row[0]: _metric_card("Divisions assessed", len(divisions), "Category used when division is not supplied")
        with row[1]: _metric_card("Top-risk division", executive["top_risk_division"], "Highest recovery priority", "amber")
        with row[2]: _metric_card("Division exposure", _money(sum(v["revenue_at_risk"] for v in divisions)), "Across the governed portfolio")
        st.markdown("### Division risk comparison")
        _risk_score_chart(divisions, "division", "Division")
        _styled_table(_with_inr(divisions, "revenue_at_risk", "expected_recovery"), {
            "division":"Division", "submitted_skus":"SKUs", "affected_skus":"Affected",
            "critical_skus":"Critical", "affected_rate":"Affected rate (%)", "risk_score":"Risk score",
            "risk_level":"Risk tier", "root_cause":"Top driver", "revenue_at_risk":"Exposure (INR)",
            "expected_recovery":"Recovery (INR)", "priority":"Priority", "owner":"Owner",
            "recommended_action":"Recommended intervention",
        }, 480)
        st.caption("When an uploaded Division field is absent, Category is used as the fallback. Risk uses the same governed five-factor formula as Vendor Intelligence.")

    with tabs[4]:
        st.subheader("Revenue & Customer Impact")
        row = st.columns(4)
        with row[0]: _metric_card("Revenue at risk", _money(revenue["revenue_at_risk"]), _commercial_input_quality(revenue), "red" if revenue["revenue_at_risk"] else "green")
        with row[1]: _metric_card("Expected recovery", _money(revenue["expected_recovery"]), f'{revenue["recovery_rate"]:.1f}% recovery rate', "green")
        with row[2]: _metric_card("Residual revenue risk", _money(revenue["residual_revenue_risk"]), "After expected recovery", "amber")
        with row[3]: _metric_card("Margin at risk", _money(revenue["margin_at_risk"]), "Gross-margin exposure", "red" if revenue["margin_at_risk"] else "green")
        secondary = st.columns(2)
        with secondary[0]: _metric_card("CX risk", customer["risk_level"], f'{customer["risk_score"]:.1f}% average score · {customer["affected_skus"]} affected SKUs', "amber" if customer["affected_skus"] else "green")
        with secondary[1]: _metric_card("Actual-input coverage", f'{revenue["actual_input_coverage"]:.1f}%', _commercial_input_quality(revenue))
        st.markdown("### Calculation contract")
        st.info(f"Revenue: {revenue['formula']} {revenue['fallback']}\n\nCustomer score: {customer['formula']}")
        _financial_and_cx_charts(intelligence["sku"])
        st.markdown("### Consolidated recovery priorities")
        recovery_priorities = _recovery_priority_summary(intelligence["sku"])
        _styled_table(_with_inr(recovery_priorities, "revenue_at_risk", "expected_recovery", "margin_at_risk", "residual_revenue_risk"), {
            "division":"Division", "affected_skus":"Unique affected SKUs", "critical_skus":"Critical SKUs",
            "top_driver":"Primary root cause", "cx_risk_score":"Average CX risk (%)",
            "revenue_at_risk":"Revenue at risk (INR)", "expected_recovery":"Expected recovery (INR)",
            "residual_revenue_risk":"Residual risk (INR)", "margin_at_risk":"Margin at risk (INR)",
            "owner":"Owner", "action":"Leadership action",
        })
        st.caption("SKU-level records are intentionally kept out of the page. Use the downloads below for detailed investigation and execution.")
        export_rows = intelligence["sku"]
        st.download_button(
            "Download leadership recovery dataset", pd.DataFrame(export_rows).to_csv(index=False).encode("utf-8"),
            "catalogiq_leadership_recovery.csv", "text/csv", width="stretch",
        )
        st.download_button(
            "Download standardized agent output", json.dumps(intelligence, indent=2).encode("utf-8"),
            "catalogiq_agent_output.json", "application/json", width="stretch",
        )


def render_app() -> None:
    st.set_page_config(page_title="CatalogIQ Pro", page_icon="CO", layout="wide")
    _inject_theme()
    from standalone_presentation import apply_theme
    apply_theme()
    from workflow_connection import workflow
    testing=st.toggle('Standalone testing mode',value=False,help='Use an isolated direct upload to test Catalog rules; no shared requests are created.')
    if not testing:
        from retail_workflow.stages import catalog as connected_catalog
        import sys
        connected_catalog(sys.modules[__name__]);return
    st.warning('Standalone test portfolio: approvals and receipts here do not authorize the connected workflow.')
    if st.session_state.get("ui_version") != "catalog-ops-6":
        st.session_state.pop("last_workflow", None)
        st.session_state["ui_version"] = "catalog-ops-6"
    repo = repository()

    st.markdown('<div class="section-kicker">Independent pre-ERP orchestration</div>', unsafe_allow_html=True)
    st.title("CatalogIQ Pro")
    with st.expander("Item onboarding versus Catalog — which dataset goes here?"):
        st.write("Item onboarding checks the initial SKU record and its vendor dependency. Catalog checks richer product content, category attributes and publication policy, then tracks corrections, human approval and simulated ERP handoff.")
        st.caption("Connected mode receives item versions from Onboarding and accepts enrichment for those same SKUs. Direct intake is available only in this isolated testing mode.")
        st.caption("Currency contract: price and commercial values are INR. Explicit missing/non-INR currency values are rejected; this app does not convert currencies.")
    st.caption("Catalog specialist workbench · deterministic controls · cycle decisions in Retail Intelligence")
    st.link_button("Open retail decision workspace", __import__("os").environ.get("RETAIL_APP_URL", "http://localhost:8508"))
    st.caption("Validation intelligence, accountable bottlenecks and faster retail launch decisions")
    st.markdown(
        '<div class="hero-panel"><div class="hero-title">Synthetic portfolio environment</div>'
        '<div class="hero-copy">Every decision is deterministic and auditable. Human approval is mandatory, '
        'and ERP creation is simulated—no production records are created.</div></div>',
        unsafe_allow_html=True,
    )
    current_items = repo.list_current_items()
    all_assessments = get_catalog_agent_assessments(repo)
    latest_by_agent = {(value["entity_id"], value["agent_name"]): value for value in all_assessments}
    exception_skus = {
        sku for (sku, agent), value in latest_by_agent.items()
        if agent in {"CATALOG_QUALITY_AGENT", "POLICY_VALIDATION_AGENT"} and value["status"] != "PASS"
    }
    quality_exception_count = len(exception_skus)
    critical_exception_skus = {
        sku for (sku, agent), value in latest_by_agent.items()
        if agent in {"CATALOG_QUALITY_AGENT", "POLICY_VALIDATION_AGENT"}
        and any(finding.get("severity") == "CRITICAL" for finding in value.get("findings", []))
    }
    approval_eligible_skus = {
        item["sku"] for item in current_items
        if item.get("lifecycle_status") == "PENDING_HUMAN_APPROVAL" and item["sku"] not in exception_skus
    }
    approval_eligible_count = len(approval_eligible_skus)
    _workflow_strip(current_items, quality_exception_count, approval_eligible_count)

    workspace = st.radio(
        "Workspace",
        ["Leadership Intelligence", "Onboarding & Workflow"],
        horizontal=True,
        label_visibility="collapsed",
        key="catalogiq_workspace",
    )
    if workspace == "Leadership Intelligence":
        _leadership_workspace(repo)
        return

    overview, intake, exceptions, approval, audit = st.tabs([
        "Operations Summary", "Item Onboarding", "Information Quality",
        "Human Approval & ERP Handoff", "Audit & Data",
    ])
    quality = bottlenecks = exceptions
    history = about = audit

    with overview:
        snapshot = get_catalog_domain_snapshot(repo)
        workflow = get_catalog_workflow_metrics(repo, approval_eligible_skus)
        actionables = get_catalog_actionable_summary(repo)
        bottleneck_rows = get_catalog_bottleneck_summary(repo)
        _executive_brief(snapshot, workflow, approval_eligible_count, len(critical_exception_skus))
        st.subheader("Executive control tower")
        st.caption("Leadership view of launch readiness, delay exposure, accountable teams and required action.")
        total = snapshot["evaluated_skus"] or 1
        approval_pct = approval_eligible_count / total * 100
        exception_pct = quality_exception_count / total * 100
        blocker_pct = snapshot["critical_blocker_count"] / total * 100
        correction_count = sum(item.get("lifecycle_status") == "REWORK_REQUIRED" for item in current_items)
        at_risk_count = len(exception_skus | {item["sku"] for item in current_items if item.get("lifecycle_status") in {"REWORK_REQUIRED", "ON_HOLD"}})
        projected_delay = max((row["estimated_delay_days"] for row in bottleneck_rows), default=0.0)
        first = st.columns(4)
        with first[0]: _metric_card("Launch pipeline", snapshot["evaluated_skus"], "Unique current SKUs across all uploads")
        with first[1]: _metric_card("Validation cleared", approval_eligible_count, f"{approval_pct:.1f}% eligible for approval", "green")
        with first[2]: _metric_card("Launches at risk", at_risk_count, f"{at_risk_count / total * 100:.1f}% need intervention", "amber" if at_risk_count else "green")
        with first[3]: _metric_card("Projected launch delay", f"{projected_delay:.2f} days", "Oldest bottleneck beyond SLA", "red" if projected_delay else "green")

        st.markdown("### Leadership action queue")
        st.caption("Teams are ranked by SLA breaches and affected launch volume. One SKU may contribute to multiple team bottlenecks.")
        if bottleneck_rows:
            _styled_table(bottleneck_rows[:6], {
                "team":"Team", "affected_skus":"Affected SKUs", "sla_breaches":"SLA breaches",
                "estimated_delay_days":"Delay (days)", "recommended_action":"Required action",
            })
        else:
            _empty("No launch bottlenecks", "No team-level validation bottlenecks require leadership intervention.")

    with intake:
        st.info('Use Upload or replace data in Leadership Intelligence for the single standalone test intake. Connected mode receives item requests from Onboarding.')

    with quality:
        st.subheader("Information quality & bottlenecks")
        st.caption("Which information defects are delaying launch, where they are concentrated, and which internal team owns the resolution.")
        assessments = [a for a in get_catalog_agent_assessments(repo) if a["agent_name"] == "CATALOG_QUALITY_AGENT"]
        latest = {a["entity_id"]: a for a in assessments}
        values = list(latest.values())
        if not values:
            _empty("No quality assessments", "Run Item Intake to create the first catalog assessment.")
        else:
            summary = st.columns(3)
            pass_with_warnings = sum(a["status"] == "PASS_WITH_WARNINGS" for a in values)
            failed = sum(a["status"] == "FAIL" for a in values)
            passed = sum(a["status"] == "PASS" for a in values)
            total_quality = len(values) or 1
            with summary[0]: _metric_card("Pass with warnings", pass_with_warnings, f"{pass_with_warnings / total_quality * 100:.1f}% of evaluated SKUs", "amber")
            with summary[1]: _metric_card("Fail", failed, f"{failed / total_quality * 100:.1f}% of evaluated SKUs", "red")
            with summary[2]: _metric_card("Pass", passed, f"{passed / total_quality * 100:.1f}% of evaluated SKUs", "green")

            _brand_quality_intelligence(current_items, latest_by_agent)

            show_analysis = True
            st.markdown("### Detailed validation analysis")
            item_lookup = {item["sku"]: item for item in current_items}
            category_rows = []
            for category in sorted({item.get("category") or "Unknown" for item in current_items}):
                category_values = [value for value in values if (item_lookup.get(value["entity_id"], {}).get("category") or "Unknown") == category]
                if category_values:
                    score = sum(value["readiness_score"] for value in category_values) / len(category_values)
                    category_rows.append({"Category": category, "Average score": score, "Label": f"{score:.1f}%"})
            category_frame = pd.DataFrame(category_rows)
            category_chart = alt.Chart(category_frame).mark_bar(cornerRadiusEnd=6, color="#7088f2").encode(
                y=alt.Y("Average score:Q", scale=alt.Scale(domain=[0, 100]), title="Average readiness (%)"),
                x=alt.X("Category:N", sort="-y", title=None),
                tooltip=["Category:N", alt.Tooltip("Average score:Q", format=".1f")],
            )
            category_labels = alt.Chart(category_frame).mark_text(dy=-9, color="#eef2ff", fontWeight="bold").encode(
                y="Average score:Q", x=alt.X("Category:N", sort="-y"), text="Label:N",
            )

            agent_rows = []
            for agent in ["ITEM_INTAKE_AGENT", "POLICY_VALIDATION_AGENT", "CATALOG_QUALITY_AGENT"]:
                agent_values = [value for (sku, name), value in latest_by_agent.items() if name == agent]
                if agent_values:
                    score = sum(value["readiness_score"] for value in agent_values) / len(agent_values)
                    agent_rows.append({"Agent": _label(agent.replace("_AGENT", "")), "Average score": score, "Label": f"{score:.1f}%"})
            agent_frame = pd.DataFrame(agent_rows)
            agent_chart = alt.Chart(agent_frame).mark_bar(cornerRadiusEnd=6, color="#74bea3").encode(
                y=alt.Y("Average score:Q", scale=alt.Scale(domain=[0, 100]), title="Average score (%)"),
                x=alt.X("Agent:N", sort="-y", title=None),
                tooltip=["Agent:N", alt.Tooltip("Average score:Q", format=".1f")],
            )
            agent_labels = alt.Chart(agent_frame).mark_text(dy=-9, color="#eef2ff", fontWeight="bold").encode(
                y="Average score:Q", x=alt.X("Agent:N", sort="-y"), text="Label:N",
            )

            mix_counts = pd.Series([item.get("category") or "Unknown" for item in current_items]).value_counts().rename_axis("Category").reset_index(name="Count")
            mix_counts["Composition"] = mix_counts["Count"] / len(current_items) * 100
            mix_counts["Label"] = mix_counts["Composition"].map(lambda value: f"{value:.1f}%")
            mix_chart = alt.Chart(mix_counts).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, color="#917be2").encode(
                x=alt.X("Category:N", sort="-y", title=None), y=alt.Y("Count:Q", title="SKU count"),
                tooltip=["Category:N", "Count:Q", alt.Tooltip("Composition:Q", format=".1f", title="% of catalog")],
            )
            mix_labels = alt.Chart(mix_counts).mark_text(dy=-10, color="#e8edf7", fontWeight="bold").encode(
                x=alt.X("Category:N", sort="-y"), y="Count:Q", text="Label:N",
            )

            chart_left, chart_right = st.columns(2)
            with chart_left:
                if show_analysis:
                    st.markdown("#### Readiness by category")
                    _chart(category_chart + category_labels, 280)
                    st.markdown("#### Agent readiness")
                    _chart(agent_chart + agent_labels, 240)
            with chart_right:
                if show_analysis:
                    st.markdown("#### Catalog mix")
                    _chart(mix_chart + mix_labels, 350)

    with bottlenecks:
        st.markdown("### Top information defects")
        st.caption("Each attribute appears once. Affected SKUs are consolidated across all rules and agents; one SKU is counted once per attribute.")
        attribute_rows = [
            {
                "attribute": row["actionable"], "affected_skus": row["affected_skus"],
                "portfolio_pct": row["composition_pct"], "severity": row["severity"],
                "required_action": row["recommended_action"],
            }
            for row in actionables[:10]
        ]
        _styled_table(attribute_rows, {
            "attribute":"Attribute requiring action", "affected_skus":"Affected SKUs",
            "portfolio_pct":"% of portfolio", "severity":"Severity", "required_action":"Required action",
        })

        vendor_items: dict[tuple[str, str], set[str]] = {}
        vendor_brands: dict[tuple[str, str], set[str]] = {}
        for item in current_items:
            if item["sku"] not in exception_skus:
                continue
            key = (item.get("vendor_id") or "—", item.get("vendor_name") or "Unknown vendor")
            vendor_items.setdefault(key, set()).add(item["sku"])
            vendor_brands.setdefault(key, set()).add(item.get("brand") or "Unspecified")
        vendor_rows = []
        affected_total = len(exception_skus) or 1
        for (vendor_id, vendor_name), skus in vendor_items.items():
            vendor_rows.append({
                "vendor": vendor_name, "vendor_id": vendor_id,
                "brands": ", ".join(sorted(vendor_brands[(vendor_id, vendor_name)])),
                "affected_skus": len(skus), "composition_pct": round(len(skus) / affected_total * 100, 1),
            })
        vendor_rows.sort(key=lambda row: (-row["affected_skus"], row["vendor"]))
        st.markdown("### Top 5 vendors contributing to information defects")
        st.caption("% composition = vendor's affected SKUs divided by all unique SKUs requiring information-quality action.")
        _styled_table(vendor_rows[:5], {
            "vendor":"Vendor", "vendor_id":"Vendor ID", "brands":"Brand(s)",
            "affected_skus":"Affected SKUs", "composition_pct":"% composition",
        })

    with approval:
        st.subheader("Human approval & ERP handoff")
        st.caption("Step 3 of 4 · Record governed human decisions, then prepare approved items for simulated ERP handoff.")
        items = repo.list_current_items()
        if not items:
            _empty("No items awaiting action", "Complete an intake workflow first.")
        else:
            latest_by_sku = {d["sku"]: d for d in repo.list_decisions()}
            queue = []
            queue_priority = {"PENDING_HUMAN_APPROVAL": 1, "APPROVED": 2, "ERP_HANDOFF_READY": 3, "ON_HOLD": 4}
            for item in items:
                is_cleared_pending = item["lifecycle_status"] == "PENDING_HUMAN_APPROVAL" and item["sku"] in approval_eligible_skus
                if is_cleared_pending or item["lifecycle_status"] in {"APPROVED", "ERP_HANDOFF_READY", "ON_HOLD"}:
                    governed = latest_by_sku.get(item["sku"], {})
                    queue.append({
                        "sku": item["sku"], "product": item["product_name"],
                        "status": item["lifecycle_status"],
                        "readiness": governed.get("composite_readiness", 0),
                        "blockers": len(governed.get("critical_blockers", [])),
                        "priority": queue_priority[item["lifecycle_status"]],
                    })
            queue.sort(key=lambda row: (row["priority"], -row["blockers"], row["sku"]))
            human_queue = [row for row in queue if row["status"] == "PENDING_HUMAN_APPROVAL"]
            handoff_queue = [row for row in queue if row["status"] in {"APPROVED", "ERP_HANDOFF_READY"}]
            hold_queue = [row for row in queue if row["status"] == "ON_HOLD"]
            st.markdown("### Approval decision queue")
            st.caption("Quality-cleared SKUs awaiting an explicit human decision. Approving an item does not send it to ERP.")
            _styled_table(human_queue[:15], {
                "sku":"SKU", "product":"Product", "status":"Workflow stage",
                "readiness":"Readiness", "blockers":"Blockers",
            }, 250)
            st.markdown("### ERP handoff queue")
            st.caption("Human-approved SKUs waiting for handoff preparation, followed by items already marked ERP-ready.")
            _styled_table(handoff_queue[:15], {
                "sku":"SKU", "product":"Product", "status":"Workflow stage", "readiness":"Readiness",
            }, 220)
            if hold_queue:
                with st.expander(f"On-hold items ({len(hold_queue)})"):
                    _styled_table(hold_queue, {"sku":"SKU", "product":"Product", "status":"Workflow stage"})
            st.markdown("### Review selected item")
            queue_skus = {row["sku"] for row in queue}
            item_by_sku = {item["sku"]: item for item in items}
            review_items = [item_by_sku[row["sku"]] for row in queue if row["sku"] in item_by_sku]
            review_skus = [item["sku"] for item in review_items]
            # Workflow actions can remove the previous selection from the queue.
            # Clear that stale widget value before rendering the new options.
            if st.session_state.get("approval_sku") not in review_skus:
                st.session_state.pop("approval_sku", None)
            if not review_items:
                _empty("No items awaiting review", "The approval and ERP handoff queues are currently clear.")
                return
            sku = st.selectbox("Choose an item", review_skus, key="approval_sku",
                format_func=lambda s: f"{s} · {next(i['product_name'] for i in review_items if i['sku']==s)}")
            current = next((i for i in review_items if i["sku"] == sku), review_items[0])
            decisions = repo.list_decisions(sku)
            decision = decisions[-1] if decisions else None
            left, right = st.columns([1, 1.35])
            with left:
                st.markdown(f'<span class="status-pill">{_label(current["lifecycle_status"])}</span>', unsafe_allow_html=True)
                st.markdown(f"### {current['product_name']}")
                st.caption(f"{sku} · {current['category']} · Revision {current['revision_number']}")
                st.markdown('<div class="detail-card">' +
                    f'<div class="detail-row"><span class="detail-key">Vendor</span><span class="detail-value">{current["vendor_name"] or current["vendor_id"]}</span></div>' +
                    f'<div class="detail-row"><span class="detail-key">Price</span><span class="detail-value">₹{current["price"]:,.2f}</span></div>' +
                    f'<div class="detail-row"><span class="detail-key">Brand</span><span class="detail-value">{current["brand"] or "—"}</span></div></div>', unsafe_allow_html=True)
            with right:
                if decision:
                    blocker_count, warning_count = len(decision["critical_blockers"]), len(decision["warnings"])
                    tone = "red" if blocker_count else "green"
                    row = st.columns(3)
                    with row[0]: _metric_card("Recommendation", _label(decision["decision"]), "Agent recommendation", tone)
                    with row[1]: _metric_card("Readiness", f'{decision["composite_readiness"]:.0f}%', "Composite score")
                    with row[2]: _metric_card("Exceptions", blocker_count + warning_count, f"{blocker_count} blockers · {warning_count} warnings", "red" if blocker_count else "amber" if warning_count else "green")
                    if blocker_count:
                        st.error(_findings_text(decision["critical_blockers"]))
                    elif warning_count:
                        st.warning(_findings_text(decision["warnings"]))
                    else:
                        st.success("All governed checks passed. Human approval may proceed.")
            orchestrator = CatalogOperationsOrchestrator(repo)
            status = current["lifecycle_status"]
            action_guidance = {
                "PENDING_HUMAN_APPROVAL": (
                    "Approve item records human approval and moves the SKU to the ERP handoff queue. "
                    "Request correction removes it from approval until a corrected version passes validation. "
                    "Place on hold pauses processing without rejecting the SKU."
                ),
                "APPROVED": (
                    "Prepare ERP-ready handoff confirms the approved SKU is ready for a simulated downstream payload. "
                    "Request correction reopens the item before handoff; Place on hold pauses it."
                ),
                "ERP_HANDOFF_READY": (
                    "Mark created in ERP simulation completes the demonstration lifecycle. No production ERP record is created."
                ),
                "ON_HOLD": (
                    "Release hold returns a cleared SKU to Human Approval. If its latest decision contains critical blockers, "
                    "it returns to Correction Required instead."
                ),
            }
            st.markdown("#### What happens when you act")
            st.info(action_guidance.get(status, "The selected action is recorded in the governed audit history."))
            reason = st.text_input("Decision note", placeholder="Add a concise reason for the audit history")
            primary = secondary = None
            if status == "PENDING_HUMAN_APPROVAL": primary = ("Approve item", "APPROVE"); secondary = ("Request correction", "RETURN_FOR_REWORK")
            elif status == "APPROVED": primary = ("Prepare ERP-ready handoff", "PREPARE_ERP_HANDOFF"); secondary = ("Request correction", "RETURN_FOR_REWORK")
            elif status == "ERP_HANDOFF_READY": primary = ("Mark created in ERP simulation", "MARK_CREATED_IN_ERP_SIMULATION")
            elif status == "ON_HOLD": primary = ("Release hold", "RELEASE_HOLD")
            action_cols = st.columns([1, 1, 1.4])
            chosen = None
            if primary and action_cols[0].button(primary[0], type="primary", width="stretch"): chosen = primary[1]
            if secondary and action_cols[1].button(secondary[0], width="stretch"): chosen = secondary[1]
            if status in {"PENDING_HUMAN_APPROVAL", "REWORK_REQUIRED", "APPROVED"} and action_cols[2].button("Place on hold", width="stretch"): chosen = "PLACE_ON_HOLD"
            if chosen:
                try:
                    target = orchestrator.transition(sku, chosen, reason.strip() or "HUMAN_WORKFLOW_ACTION")
                    st.success(f"{sku} moved to {_label(target.value)}."); st.rerun()
                except (ValueError, KeyError) as exc: st.error(str(exc))

    # Post-live vendor-requested amendments are intentionally deferred from this pre-live workflow.
    if False:
        st.subheader("Rework intelligence")
        st.caption("Step 4 of 4 · Track corrections, recurring defects, approval loops, and downstream delay.")
        metrics = get_catalog_rework_metrics(repo)
        cols = st.columns(4)
        with cols[0]: _metric_card("Rework rate", f'{metrics["rework_rate"]:.0f}%', "SKUs with material changes", "amber")
        with cols[1]: _metric_card("Revisions / SKU", f'{metrics["average_revisions_per_sku"]:.1f}', "Average immutable versions")
        with cols[2]: _metric_card("Resolution time", f'{metrics["average_resolution_hours"]:.1f} h', "Average resolved cycle")
        with cols[3]: _metric_card("Downstream delay", f'{metrics["downstream_delay_hours"]:.1f} h', "Operational proxy")
        if not metrics["rework_by_attribute"]:
            _empty("No rework recorded yet", "Upload the correction dataset after the approval-ready dataset to generate version and rework history.")
        else:
            left, right = st.columns(2)
            with left:
                st.markdown("### Top changed attributes")
                attribute_df = pd.DataFrame(metrics["rework_by_attribute"]).rename(columns={"attribute_name":"Attribute", "count":"Changes"})
                attribute_df["Share"] = attribute_df["Changes"] / attribute_df["Changes"].sum() * 100
                attribute_df["Label"] = attribute_df["Share"].map(lambda value: f"{value:.1f}%")
                attribute_bars = alt.Chart(attribute_df).mark_bar(cornerRadiusEnd=5, color="#f4b860").encode(
                    y=alt.Y("Changes:Q", title="Change events"),
                    x=alt.X("Attribute:N", sort="-y", title=None),
                    tooltip=["Attribute:N", "Changes:Q", alt.Tooltip("Share:Q", title="% of rework", format=".1f")],
                )
                attribute_labels = alt.Chart(attribute_df).mark_text(dy=-9, color="#eef2ff", fontWeight="bold").encode(
                    y="Changes:Q", x=alt.X("Attribute:N", sort="-y"), text="Label:N",
                )
                _chart(attribute_bars + attribute_labels, 260)
                st.markdown("### Rework source"); _styled_table(metrics["rework_by_source"], {"source":"Source", "count":"Events"})
            with right:
                st.markdown("### Category concentration")
                category_rework_df = pd.DataFrame(metrics["rework_by_category"]).rename(columns={"category":"Category", "count":"Events"})
                category_rework_df["Share"] = category_rework_df["Events"] / category_rework_df["Events"].sum() * 100
                category_rework_df["Label"] = category_rework_df["Share"].map(lambda value: f"{value:.1f}%")
                category_rework_bars = alt.Chart(category_rework_df).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, color="#9a7cf4").encode(
                    x=alt.X("Category:N", sort="-y", title=None),
                    y=alt.Y("Events:Q", title="Rework events"),
                    tooltip=["Category:N", "Events:Q", alt.Tooltip("Share:Q", title="% of rework", format=".1f")],
                )
                category_rework_labels = alt.Chart(category_rework_df).mark_text(dy=-10, color="#e8edf7", fontWeight="bold").encode(
                    x=alt.X("Category:N", sort="-y"), y="Events:Q", text="Label:N",
                )
                _chart(category_rework_bars + category_rework_labels, 260)
                st.markdown("### Approval loops"); _styled_table(metrics["highest_approval_loops"], {"sku":"SKU", "revisions":"Revisions"})

    with history:
        st.subheader("Item journey & audit history")
        st.caption("Trace decisions, ownership, stage elapsed time and governed version changes for each SKU.")
        items = repo.list_current_items()
        if not items:
            _empty("No audit trail yet", "Workflow and decision events appear here after intake.")
        else:
            sku = st.selectbox("Choose an item", [i["sku"] for i in items], key="history_sku",
                format_func=lambda s: f"{s} · {next(i['product_name'] for i in items if i['sku']==s)}")
            current = next(i for i in items if i["sku"] == sku)
            events = get_catalog_domain_events(repo, sku)
            timeline_rows = []
            previous_time = None
            for event in events:
                raw_time = event.get("occurred_at")
                try:
                    event_time = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    event_time = None
                elapsed_days = max(0.0, (event_time - previous_time).total_seconds() / 86400) if event_time and previous_time else 0.0
                timeline_rows.append({
                    "when": event_time.strftime("%d %b %Y, %I:%M %p") if event_time else raw_time,
                    "event": _label(event.get("event_type")),
                    "from": _label(event.get("previous_status")),
                    "to": _label(event.get("new_status")),
                    "owner": _label(event.get("source")),
                    "elapsed_days": round(elapsed_days, 2),
                    "sla": "Within 1 day" if elapsed_days <= 1 else "Breached",
                })
                if event_time:
                    previous_time = event_time
            total_elapsed = sum(row["elapsed_days"] for row in timeline_rows)
            breached_stages = sum(row["sla"] == "Breached" for row in timeline_rows)
            h1, h2, h3, h4 = st.columns(4)
            with h1: _metric_card("Current status", _label(current["lifecycle_status"]), "Latest lifecycle state")
            with h2: _metric_card("Revision", current["revision_number"], "Immutable item version")
            with h3: _metric_card("Journey TAT", f"{total_elapsed:.2f} days", "Recorded stage elapsed time")
            with h4: _metric_card("Stage SLA", "Met" if not breached_stages else "Breached", f"{breached_stages} breached stages", "green" if not breached_stages else "red")
            st.caption(f'Audit reference: {current["workflow_run_id"][:8].upper()}')
            detail_tabs = st.tabs(["Timeline", "Agent assessments", "Decisions", "Version changes"])
            with detail_tabs[0]: _styled_table(timeline_rows, {"when":"When", "event":"Event", "from":"From", "to":"To", "owner":"Owner", "elapsed_days":"Elapsed days", "sla":"SLA"})
            with detail_tabs[1]:
                rows = [{"agent":_label(a["agent_name"]), "score":a["readiness_score"], "status":_label(a["status"]), "summary":_findings_text(a["findings"])} for a in repo.list_assessments(sku)]
                _styled_table(rows, {"agent":"Agent", "score":"Score", "status":"Status", "summary":"Summary"})
            with detail_tabs[2]: _styled_table(repo.list_decisions(sku), {"decided_at":"When", "decision":"Recommendation", "composite_readiness":"Readiness", "critical_blockers":"Blockers", "warnings":"Warnings"})
            with detail_tabs[3]: _styled_table(repo.list_rework_events(sku), {"attribute_name":"Attribute", "previous_value":"Before", "updated_value":"After", "source":"Source", "resolution_hours":"Hours"})

    with about:
        with st.expander("Data dictionary & downloads"):
            st.caption("Test clean onboarding, validation failures, corrections and governed version history.")
            dataset_dir = Path("outputs/catalog_operations_test_datasets")
            downloads = [
                ("Approval-ready items", "01_approval_ready_items.csv"),
                ("Mixed validation cases", "02_mixed_validation_cases.csv"),
                ("Re-upload corrections", "03_reupload_corrections.csv"),
                ("Large catalog", "04_large_catalog_250_skus.csv"),
                ("Realistic vendor & division intelligence", "08_realistic_vendor_division_intelligence_480_skus.csv"),
                ("Multi-defect overlap evaluation", "09_multi_defect_overlap_480_skus.csv"),
            ]
            cards = st.columns(2)
            for index, (title, filename) in enumerate(downloads):
                with cards[index % 2]:
                    path = dataset_dir / filename
                    if path.exists(): st.download_button(title, path.read_bytes(), filename, "text/csv", width="stretch")
            dictionary = [
                ("sku", "Required", "Stable supplier/item identifier"), ("vendor_id", "Required", "Submitting vendor identifier"),
                ("product_name", "Required", "Customer-facing title"), ("category", "Required", "Publication category"),
                ("description", "Optional", "Customer-facing description"), ("price", "Required", "Non-negative price"),
                ("gtin", "Optional", "Valid product identifier"), ("image_url", "Optional", "Absolute product image URL"),
                ("monthly_sales", "Recommended", "Monthly SKU revenue in INR"),
                ("units_sold", "Recommended", "Monthly units when monthly_sales is absent"),
                ("division", "Recommended", "Merchandising division; category is used as fallback"),
                ("return_rate", "Recommended", "SKU return rate used in customer-risk scoring"),
                ("rating", "Recommended", "Customer rating used in customer-risk scoring"),
                ("vendor_sla", "Recommended", "Vendor SLA compliance percentage"),
            ]
            st.dataframe(pd.DataFrame(dictionary, columns=["Field", "Requirement", "Definition"]), width="stretch", hide_index=True)
            st.caption("Synthetic data only · Human approval mandatory · ERP creation always simulated")

