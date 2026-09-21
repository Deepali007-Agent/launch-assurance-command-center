"""Vendor IQ Pro — Vendor Intelligence & Onboarding Orchestration."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import importlib
import standardized_app
# Refresh the interface module on rerun while retaining uploaded session data.
render_standardized_app = importlib.reload(standardized_app).render_app

render_standardized_app()
st.stop()

from data_factory import make_dataset, write_datasets
from kpis import REGISTRY, registry_frame, results_frame
from item_onboarding import assess_items, sample_items
from publishing import build_publication, publication_state, publish
from service import VendorIQService

st.set_page_config(page_title="Onboarding Intelligence", page_icon="◈", layout="wide")
st.markdown("""
<style>
  .stApp {background: #07111f; color: #e7edf7}
  [data-testid="stSidebar"] {background: #0b1728; border-right: 1px solid #20314a}
  [data-testid="stMetric"] {background: linear-gradient(145deg,#102139,#0c1a2d); border:1px solid #243b5a; padding:16px; border-radius:14px}
  [data-testid="stMetricLabel"] {color:#9bb0cb}
  [data-testid="stMetricValue"] {color:#f4f7fb}
  .block-container {padding-top: 2rem; max-width: 1500px}
  h1,h2,h3 {letter-spacing:-.02em}
  .eyebrow {color:#55d6be; font-size:.78rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase}
  .subtle {color:#9bb0cb}
  .notice {padding:14px 16px;border-radius:10px;background:#102139;border-left:3px solid #55d6be;margin:8px 0 16px}
  .danger {border-left-color:#ff6b7a}
  .stTabs [data-baseweb="tab-list"] {gap:10px}
  .stTabs [data-baseweb="tab"] {background:#0c1a2d;border-radius:8px;padding:8px 16px}
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def service():
    write_datasets(ROOT / "data")
    svc = VendorIQService(ROOT / "data" / "vendor_iq.db")
    current = svc.repo.vendors()
    if not current or "planned_purchase_value" not in current[0]:
        svc.ingest(make_dataset(500, "mixed"), replace=True)
    return svc


svc = service()
vendors, assessments, audit = svc.snapshot()
kpis = svc.kpis()
if "item_onboarding_data" not in st.session_state:
    st.session_state.item_onboarding_data = sample_items()
item_detail_current, item_summary_current = assess_items(st.session_state.item_onboarding_data)

st.sidebar.markdown("<div class='eyebrow'>Retail intelligence ecosystem</div>", unsafe_allow_html=True)
st.sidebar.title("◈ Onboarding Intelligence")
st.sidebar.caption("Vendor Onboarding + Item Onboarding")
st.sidebar.divider()
st.sidebar.info("This demonstration simulates ERP handoff. Production creation requires governed approval and an authorised ERP integration.")

st.markdown("<div class='eyebrow'>Vendor operations command centre</div>", unsafe_allow_html=True)
st.title("Onboarding Intelligence")
st.caption("Vendor specialist workbench · deterministic controls · cycle decisions in Retail Intelligence")
st.link_button("Open retail decision workspace", __import__("os").environ.get("RETAIL_APP_URL", "http://localhost:8508"))
st.caption("Govern vendor and item onboarding in one standalone operations workspace while preserving separate calculations and ownership.")

tabs = st.tabs(["Control Tower", "Vendor Onboarding", "Item Onboarding", "Risk & Compliance", "Approval & Handoff", "Audit & Data"])


def findings_frame():
    rows = []
    if assessments.empty:
        return pd.DataFrame()
    names = vendors.set_index("vendor_id")["legal_name"].to_dict()
    for _, a in assessments.iterrows():
        for f in a["findings"]:
            rows.append({"vendor_id": a["vendor_id"], "vendor": names.get(a["vendor_id"], a["vendor_id"]),
                         "agent": a["agent"], **f})
    return pd.DataFrame(rows)


findings = findings_frame()
FIELD_LABELS = {
    "document_expiry_date": "Document expiry",
    "validation_risk": "Unresolved validation blockers",
    "revision_number": "Repeated submission corrections",
    "tax_id": "Tax identifier",
    "document_status": "Document status",
    "incoterms": "Delivery terms (Incoterms)",
    "insurance_status": "Insurance evidence",
    "registration_id": "Company registration",
    "payment_terms": "Payment terms",
    "ethical_trade_status": "Ethical-trade evidence",
    "vendor_authorization": "Vendor authorization",
    "bank_information_status": "Bank verification",
    "minimum_order_quantity": "Minimum order quantity",
}


def business_field(field):
    return FIELD_LABELS.get(str(field), str(field).replace("_", " ").title())


def dependency_source(field):
    field = str(field)
    if field in {"validation_risk", "warning_concentration"}:
        return "Internal team"
    if field in {"payment_terms", "incoterms", "return_terms", "lead_time_days", "minimum_order_quantity", "bank_information_status"}:
        return "Shared"
    if field in {"tax_id", "registration_id", "insurance_status", "ethical_trade_status", "vendor_authorization", "document_status", "document_expiry_date"}:
        return "Vendor / external authority"
    return "Vendor"


def required_evidence(field):
    labels = {
        "tax_id":"Valid tax registration evidence", "registration_id":"Company registration evidence",
        "insurance_status":"Current approved insurance evidence", "ethical_trade_status":"Current ethical-trade evidence",
        "vendor_authorization":"Current vendor authorisation", "document_status":"Current approved document",
        "document_expiry_date":"Valid document expiry date or renewed document", "bank_information_status":"Completed secure bank verification",
        "payment_terms":"Approved payment terms", "incoterms":"Agreed delivery terms", "return_terms":"Agreed return terms",
        "lead_time_days":"Agreed lead time", "minimum_order_quantity":"Agreed valid order quantity",
        "validation_risk":"Evidence that every underlying critical finding is resolved",
    }
    return labels.get(str(field), f"Validated {business_field(field).lower()}")


def working_days_since(timestamp):
    value = pd.to_datetime(timestamp, errors="coerce", utc=True)
    if pd.isna(value):
        return None
    today = pd.Timestamp.now(tz="UTC").normalize()
    start = value.normalize()
    if start >= today:
        return 0
    return max(len(pd.bdate_range(start=start, end=today)) - 1, 0)


def workbook_bytes(sheets):
    """Create a review-ready Excel workbook entirely in memory."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            safe_name = sheet_name[:31]
            frame.to_excel(writer, sheet_name=safe_name, index=False)
            worksheet = writer.sheets[safe_name]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cell in worksheet[1]:
                cell.font = cell.font.copy(bold=True, color="FFFFFF")
                cell.fill = cell.fill.copy(fill_type="solid", fgColor="17365D")
            for column in worksheet.columns:
                values = [str(cell.value or "") for cell in column]
                worksheet.column_dimensions[column[0].column_letter].width = min(max(max(map(len, values)) + 2, 12), 48)
    return output.getvalue()


def vendor_action_list():
    """One operational row per vendor, with detailed attributes rolled up."""
    if findings.empty:
        return pd.DataFrame()
    base = findings.copy()
    base["Missing / at-risk attribute"] = base["field"].map(business_field)
    base["Dependency source"] = base["field"].map(dependency_source)
    base["Required evidence"] = base["field"].map(required_evidence)
    rank = {"Critical": 0, "Warning": 1, "Pass": 2}
    base["priority_rank"] = base["severity"].map(rank).fillna(3)
    priority = base.sort_values("priority_rank").groupby("vendor_id")["severity"].first()
    base["is_rollup"] = base["field"].isin(["validation_risk", "warning_concentration"])
    has_direct = base.groupby("vendor_id")["is_rollup"].transform(lambda values: (~values).any())
    candidates = base[~base["is_rollup"] | ~has_direct].copy()
    team_precedence = {"Vendor Master Data":0, "Finance":1, "Compliance":2, "Commercial":3, "Buying":4, "Vendor Onboarding":5, "Vendor Operations":6}
    candidates["team_rank"] = candidates["owner"].map(team_precedence).fillna(99)
    primary_team = candidates.sort_values(["vendor_id", "priority_rank", "team_rank", "owner"]).drop_duplicates("vendor_id").set_index("vendor_id")["owner"]
    rolled = base.groupby(["vendor_id", "vendor"], as_index=False).agg(
        **{
            "Missing / at-risk attributes": ("Missing / at-risk attribute", lambda x: "; ".join(sorted(set(map(str, x))))),
            "Dependency sources": ("Dependency source", lambda x: "; ".join(sorted(set(map(str, x))))),
            "Required evidence": ("Required evidence", lambda x: "; ".join(sorted(set(map(str, x))))),
            "Findings": ("issue", lambda x: "; ".join(dict.fromkeys(map(str, x)))),
            "Next-action teams": ("owner", lambda x: "; ".join(sorted(set(map(str, x))))),
            "Next actions": ("how_to_fix", lambda x: "; ".join(dict.fromkeys(map(str, x)))),
            "Open issue count": ("field", "count"),
        }
    )
    rolled["Priority"] = rolled["vendor_id"].map(priority)
    rolled["Primary next-action team"] = rolled["vendor_id"].map(primary_team)
    details = vendors[["vendor_id", "status", "age_days", "source_business_unit", "strategic_tier", "planned_purchase_value"]]
    rolled = rolled.merge(details, on="vendor_id", how="left")
    rolled["Age band"] = pd.cut(rolled["age_days"], bins=[-0.001,10,20,30,40,50,float("inf")], labels=["0–10 days","11–20 days","21–30 days","31–40 days","41–50 days","Over 50 days"], include_lowest=True).astype(str)
    return rolled.rename(columns={"vendor_id":"Vendor ID", "vendor":"Vendor", "status":"Current stage", "age_days":"Age (days)", "source_business_unit":"Business unit", "strategic_tier":"Strategic tier", "planned_purchase_value":"Planned value"})


KPI_BY_KEY = {definition.key: definition for definition in REGISTRY}


def governed_definitions(keys):
    return [{
        "name": KPI_BY_KEY[key].name,
        "purpose": KPI_BY_KEY[key].purpose,
        "formula": f"{KPI_BY_KEY[key].numerator} ÷ {KPI_BY_KEY[key].denominator}" if KPI_BY_KEY[key].denominator != "Not applicable" else KPI_BY_KEY[key].numerator,
        "eligible": KPI_BY_KEY[key].eligible_population,
        "exclusions": KPI_BY_KEY[key].exclusions,
        "evidence": KPI_BY_KEY[key].required_fields,
        "open_records": KPI_BY_KEY[key].open_record_treatment,
        "target": KPI_BY_KEY[key].target or "No governed target set",
        "owner": KPI_BY_KEY[key].owner,
        "assumption": "Calculated from the latest unique vendor record and latest assessment per vendor and agent.",
    } for key in keys]


@st.dialog("How these metrics are calculated", width="large")
def metric_definition_dialog(section, definitions):
    st.caption(f"{section} · governed metric definitions")
    for definition in definitions:
        st.markdown(f"### {definition['name']}")
        st.write(definition["purpose"])
        st.markdown(f"**Formula:** {definition['formula']}")
        st.markdown(f"**Included:** {definition['eligible']}")
        st.markdown(f"**Excluded:** {definition['exclusions']}")
        st.markdown(f"**Required evidence:** {definition['evidence']}")
        if definition.get("open_records"):
            st.markdown(f"**Open-record treatment:** {definition['open_records']}")
        if definition.get("target"):
            st.markdown(f"**Target:** {definition['target']}")
        st.markdown(f"**Business owner:** {definition['owner']}")
        if definition.get("assumption"):
            st.info(f"Assumption / limitation: {definition['assumption']}")
        st.divider()

with tabs[0]:
    st.subheader("Control Tower")
    st.caption("The combined Vendor and Item Onboarding decisions that need leadership attention now.")
    vendor_total = len(vendors)
    vendor_blocked = findings.loc[findings["severity"].eq("Critical"), "vendor_id"].nunique() if not findings.empty else 0
    vendor_warning = findings.loc[findings["severity"].eq("Warning"), "vendor_id"].nunique() if not findings.empty else 0
    vendor_ready = max(vendor_total - vendor_blocked - vendor_warning, 0)
    vendor_readiness = 100 * (vendor_ready + 0.5 * vendor_warning) / vendor_total if vendor_total else 0
    combined_readiness = vendor_readiness * 0.40 + item_summary_current["readiness"] * 0.60
    combined_status = "BLOCKED" if vendor_blocked or item_summary_current["correction_required"] else "CONDITIONAL" if vendor_warning or item_summary_current["warnings"] else "READY"
    st.markdown(f"<div class='notice'><b>Combined onboarding decision: {combined_status}</b> · Vendor readiness {vendor_readiness:.1f}% (40%) · Item readiness {item_summary_current['readiness']:.1f}% (60%)</div>", unsafe_allow_html=True)
    combined = st.columns(4)
    combined[0].metric("Combined readiness", f"{combined_readiness:.1f}%", help="Governed policy: Vendor Onboarding contributes 40% and Item Onboarding contributes 60%.")
    combined[1].metric("Vendor onboarding", f"{vendor_ready:,} ready / {vendor_total:,}", help="Unique latest vendors without critical or warning findings divided by all submitted vendors.")
    combined[2].metric("Item onboarding", f"{item_summary_current['approval_ready']:,} ready / {item_summary_current['submitted']:,}", help="Unique latest SKUs with all mandatory and customer-facing onboarding fields supplied.")
    combined[3].metric("Critical interventions", f"{vendor_blocked + item_summary_current['correction_required']:,}", help="Unique critical vendors plus unique correction-required items. Vendor and item populations remain separate and are not deduplicated against each other.")
    st.markdown("### Vendor onboarding operations")
    total = len(vendors)
    risk_ids = set(findings.loc[findings["severity"] == "Critical", "vendor_id"]) if not findings.empty else set()
    cols = st.columns(4)
    cols[0].metric(
        "Vendors with critical blockers",
        f"{len(risk_ids):,}",
        help="Unique vendors with at least one unresolved critical finding. These vendors cannot proceed to approval until the blocker is resolved.",
    )
    cols[1].metric(
        "Business value blocked",
        ("Not measurable yet" if len(risk_ids) and not kpis["opportunity_at_risk"].value else kpis["opportunity_at_risk"].display),
        help="Expected purchasing value associated with currently blocked vendors. Each vendor is counted once. This is a prioritisation proxy, not realised loss or revenue at risk.",
    )
    cols[2].metric(
        "Approvals pending",
        kpis["approvals_awaiting"].display,
        help="Validation-cleared vendors waiting for a governed human approval decision. This is the current approval backlog.",
    )
    cols[3].metric(
        "Median activation time",
        kpis["median_safe_activation_days"].display,
        help="Median calendar days from acceptance of a valid submission to governed approval. Only vendors with measurable submission and approval timestamps are included.",
    )
    st.caption("Hover over the information icon on each KPI for its meaning and calculation scope. Full definitions and targets are in Audit & Data.")
    publication_payload = build_publication(vendors, assessments, kpis)
    publication = publication_state(publication_payload)
    with st.expander("Retail Intelligence Platform / Orchestration", expanded=True):
        p1, p2, p3 = st.columns(3)
        p1.metric("Publishing status", publication.get("status", "Ready to publish"),
                  help="Ready to publish means the verified Vendor Intelligence package can be sent. Published means the parent platform acknowledged it.")
        p2.metric("Orchestration run", publication_payload["orchestration_run_id"],
                  help="Stable run ID derived from the current vendor portfolio and revisions.")
        p3.metric("Destination", "Retail Intelligence Platform",
                  help="Authenticated parent intake service. Vendor data is sent only when you select Publish.")
        if publication.get("acknowledgement"):
            st.success(f"Published and acknowledged: {publication['acknowledgement'].get('acknowledgement_id', 'Accepted')}")
        elif st.button("Publish Vendor Intelligence to Retail Intelligence Platform", type="primary"):
            try:
                result = publish(publication_payload)
                st.success(f"Published and acknowledged: {result['acknowledgement'].get('acknowledgement_id', 'Accepted')}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    control_definitions = [{
        "name":"Vendors with critical blockers", "purpose":"Quantifies the current population unable to proceed safely.",
        "formula":"Count of unique open vendor IDs with at least one latest Critical assessment",
        "eligible":"Open vendors with a completed specialist assessment", "exclusions":"Rejected, completed, and unassessed vendors",
        "evidence":"Latest vendor status and latest assessment per vendor and agent", "open_records":"Current unresolved exposure only",
        "target":"No arbitrary target; expected to reduce through remediation", "owner":"Risk & Compliance",
        "assumption":"One vendor is counted once even when several agents report critical findings.",
    }] + governed_definitions(["opportunity_at_risk", "approvals_awaiting", "median_safe_activation_days"])
    if st.button("ⓘ How these metrics are calculated", key="control_metric_definitions"):
        metric_definition_dialog("Control Tower", control_definitions)

    st.markdown("### Leadership Action Queue")
    if findings.empty:
        st.success("No actions currently require leadership attention.")
    else:
        action_findings = findings.copy()
        action_findings["is_rollup"] = action_findings["field"].isin(["validation_risk", "warning_concentration"])
        has_direct = action_findings.groupby("vendor_id")["is_rollup"].transform(lambda values: (~values).any())
        candidates = action_findings[~action_findings["is_rollup"] | ~has_direct].copy()
        candidates["severity_rank"] = candidates["severity"].map({"Critical":0, "Warning":1}).fillna(2)
        team_precedence = {"Vendor Master Data":0, "Finance":1, "Compliance":2, "Commercial":3, "Buying":4, "Vendor Onboarding":5, "Vendor Operations":6}
        candidates["team_rank"] = candidates["owner"].map(team_precedence).fillna(99)
        primary = candidates.sort_values(["vendor_id", "severity_rank", "team_rank", "owner"]).drop_duplicates("vendor_id")
        owner_age = primary[["vendor_id", "owner"]].merge(vendors[["vendor_id", "age_days", "planned_purchase_value"]], on="vendor_id", how="left")
        queue = primary.groupby("owner", as_index=False).agg(
            affected_vendors=("vendor_id", "nunique"), required_action=("how_to_fix", "first"), primary_exception=("issue", "first")
        )
        exposure = owner_age.groupby("owner")["planned_purchase_value"].sum()
        queue["exposed_value"] = queue["owner"].map(exposure).fillna(0)
        queue["sla_breaches"] = queue["owner"].map(owner_age[owner_age["age_days"] > 30].groupby("owner")["vendor_id"].nunique()).fillna(0).astype(int)
        queue["exposed_value"] = queue["exposed_value"].map(lambda x: f"£{x:,.0f}")
        queue = queue.sort_values(["sla_breaches", "affected_vendors"], ascending=False).rename(columns={
            "owner":"Next-action team", "primary_exception":"Main blocker", "affected_vendors":"Vendors affected",
            "sla_breaches":"Aged over 30 calendar days", "exposed_value":"Business value blocked", "required_action":"Next action"})
        st.dataframe(queue[["Next-action team", "Main blocker", "Vendors affected", "Business value blocked", "Aged over 30 calendar days", "Next action"]], width="stretch", hide_index=True)
        reconciled_value = owner_age["planned_purchase_value"].sum()
        st.caption(f"Reconciled total: {primary['vendor_id'].nunique():,} unique vendors · £{reconciled_value:,.0f} business value counted once. Secondary teams remain in the downloadable detail.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Where vendors are in the onboarding journey")
        st.caption("Current vendor count by lifecycle stage.")
        pipeline = vendors.groupby("status").size().reset_index(name="count")
        pipeline["label"] = pipeline["count"].map(lambda value: f"{value:,}")
        chart = alt.Chart(pipeline).mark_bar(cornerRadiusEnd=5).encode(x=alt.X("count:Q", title="Number of vendors"), y=alt.Y("status:N", sort="-x", title=None), color=alt.value("#55d6be"))
        st.altair_chart(chart + chart.mark_text(align="left", dx=5, color="#e7edf7").encode(text="label:N"), width="stretch")
    with c2:
        st.markdown("### Which teams own overdue work?")
        st.caption("Open vendor cases older than 30 calendar days. This is an aging diagnostic, not an approval-SLA measure.")
        if not findings.empty:
            exposure = owner_age.assign(breached=owner_age["age_days"] > 30).groupby("owner")["breached"].sum().reset_index()
            exposure["label"] = exposure["breached"].map(lambda value: f"{value:,}")
            ch = alt.Chart(exposure).mark_bar(cornerRadiusEnd=5, color="#ff9270").encode(x=alt.X("breached:Q", title="Number of overdue vendor cases"), y=alt.Y("owner:N", sort="-x", title=None))
            st.altair_chart(ch + ch.mark_text(align="left", dx=5, color="#e7edf7").encode(text="label:N"), width="stretch")

with tabs[1]:
    st.subheader("Vendor Onboarding")
    st.markdown("<div class='notice'>Files are structurally validated before the active portfolio changes. Unknown columns are preserved in the source record for audit.</div>", unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload vendor submissions", type=["csv", "xlsx"])
    replace = st.checkbox("Replace current test portfolio", value=True, help="Replaces only after structural validation finds accepted records.")
    if uploaded:
        try:
            incoming = pd.read_excel(uploaded) if uploaded.name.lower().endswith("xlsx") else pd.read_csv(uploaded)
            accepted_preview, rejected_preview, errors = svc.validate_frame(incoming)
            a, r = st.columns(2)
            a.metric("Accepted records", len(accepted_preview), help="Structurally valid records with a non-blank, unique vendor ID in this upload.")
            r.metric("Rejected records", len(rejected_preview), help="Records rejected before portfolio replacement because the vendor ID is blank or duplicated.")
            intake_definitions = [
                {"name":"Accepted records", "purpose":"Shows how many uploaded records can enter specialist validation.", "formula":"Uploaded rows minus structurally rejected rows", "eligible":"Rows in the current uploaded file", "exclusions":"Blank or duplicate vendor IDs", "evidence":"Current upload and required-column validation", "open_records":"Not applicable", "target":"No fixed target", "owner":"Vendor Onboarding", "assumption":"Acceptance confirms structural validity only; it does not mean the vendor is approval-ready."},
                {"name":"Rejected records", "purpose":"Shows records prevented from entering the portfolio.", "formula":"Rows with a blank vendor ID plus all rows participating in a duplicate vendor ID", "eligible":"Rows in the current uploaded file", "exclusions":"Structurally accepted records", "evidence":"Current upload", "open_records":"Not applicable", "target":"0 after vendor correction", "owner":"Vendor Onboarding", "assumption":"Every occurrence of a duplicated vendor ID is rejected to avoid choosing an arbitrary winner."},
            ]
            if st.button("ⓘ How upload results are calculated", key="intake_metric_definitions"):
                metric_definition_dialog("Vendor Onboarding", intake_definitions)
            if errors:
                st.dataframe(pd.DataFrame(errors), width="stretch", hide_index=True)
            if rejected_preview:
                st.download_button("Download rejected records", pd.DataFrame(rejected_preview).to_csv(index=False), "rejected_vendor_records.csv")
            if accepted_preview and st.button("Validate and load portfolio", type="primary"):
                outcome = svc.ingest(incoming, replace=replace)
                st.success(f"Loaded {outcome['accepted']} vendors. Specialist validation agents have completed their first assessment.")
                st.cache_resource.clear(); st.rerun()
        except Exception as exc:
            st.error(f"The file could not be read: {exc}")
    st.markdown("### What runs next")
    st.write("Vendor Master Data → Compliance & Documentation → Commercial Readiness → Vendor Risk → Approval & Handoff recommendation")
    st.markdown("### Download test portfolios")
    for filename, label in [("clean_approval_ready.csv","Clean approval-ready"),("mixed_quality_500.csv","Mixed-quality · 500 records"),
                            ("correction_resubmission.csv","Correction and resubmission"),("documentation_expiry.csv","Documentation expiry")]:
        st.download_button(label, (ROOT / "data" / filename).read_bytes(), filename, key=filename)

with tabs[2]:
    st.subheader("Item Onboarding")
    st.caption("Validate item submissions before catalog-quality review. Every KPI uses the latest unique SKU and never counts multiple missing attributes as multiple items.")
    item_upload = st.file_uploader("Upload item submissions", type=["csv", "xlsx"], key="item_onboarding_upload",
                                   help="Upload one row per SKU. Duplicate or blank SKUs are treated as critical structural errors.")
    if item_upload is not None:
        try:
            uploaded_items = pd.read_excel(item_upload) if item_upload.name.lower().endswith("xlsx") else pd.read_csv(item_upload)
            if st.button("Validate and replace item portfolio", type="primary", key="validate_items"):
                st.session_state.item_onboarding_data = uploaded_items
                st.rerun()
        except Exception as exc:
            st.error(f"The item file could not be read: {exc}")
    item_detail, item_summary = assess_items(st.session_state.item_onboarding_data)
    decision_colour = "#ff6b7a" if item_summary["decision"] == "BLOCKED" else "#ffbf69" if item_summary["decision"] == "CONDITIONAL" else "#55d6be"
    st.markdown(f"<div class='notice' style='border-left-color:{decision_colour}'><b>Item onboarding decision: {item_summary['decision']}</b> — "
                f"{item_summary['correction_required']:,} critical items and {item_summary['warnings']:,} warning-only items require governed action.</div>", unsafe_allow_html=True)
    metrics = st.columns(5)
    metrics[0].metric("Submitted items", f"{item_summary['submitted']:,}", help="Unique latest SKUs in the active item-onboarding portfolio.")
    metrics[1].metric("Onboarding readiness", f"{item_summary['readiness']:.1f}%", help="Approval-ready items receive full weight; warning-only items receive half weight; correction-required items receive zero weight.")
    metrics[2].metric("Approval ready", f"{item_summary['approval_ready']:,}", help="Unique SKUs with all mandatory and customer-facing onboarding fields supplied.")
    metrics[3].metric("Review warnings", f"{item_summary['warnings']:,}", help="Unique SKUs with no structural blocker but at least one missing customer-facing field.")
    metrics[4].metric("Correction required", f"{item_summary['correction_required']:,}", help="Unique SKUs with a missing mandatory field, blank SKU or duplicated SKU.")
    st.markdown("### Item onboarding action queue")
    action_items = item_detail[item_detail["Status"].ne("Approval ready")].copy()
    if action_items.empty:
        st.success("No item-onboarding actions remain.")
    else:
        st.dataframe(action_items, width="stretch", hide_index=True)
    d1, d2 = st.columns(2)
    d1.download_button("Download item onboarding action detail", action_items.to_csv(index=False), "item_onboarding_actions.csv", "text/csv", width="stretch")
    d2.download_button("Download approval-ready items", item_detail[item_detail["Status"].eq("Approval ready")].to_csv(index=False), "item_onboarding_approval_ready.csv", "text/csv", width="stretch")
    st.markdown("### Download test portfolio")
    st.download_button("Download item-onboarding test dataset", sample_items().to_csv(index=False), "item_onboarding_test_240.csv", "text/csv")

with tabs[3]:
    st.subheader("Risk & Compliance")
    outcomes = assessments.groupby("vendor_id")["severity"].apply(lambda x: "Fail" if (x=="Critical").any() else "Pass with warnings" if (x=="Warning").any() else "Pass") if not assessments.empty else pd.Series(dtype=str)
    cols = st.columns(3)
    for col, label in zip(cols, ["Ready", "Needs review", "Blocked"]):
        source_label = {"Ready":"Pass", "Needs review":"Pass with warnings", "Blocked":"Fail"}[label]
        metric_help = {
            "Ready":"Unique vendors whose latest agent assessments contain no warnings or critical findings.",
            "Needs review":"Unique vendors with warnings but no critical finding in their latest agent assessments.",
            "Blocked":"Unique vendors with at least one critical finding in their latest agent assessments.",
        }
        col.metric(label, int((outcomes == source_label).sum()), help=metric_help[label])
    st.caption("Ready: no unresolved findings · Needs review: warnings only · Blocked: at least one critical finding")
    risk_definitions = [
        {"name":"Ready", "purpose":"Shows vendors that can proceed without risk review.", "formula":"Unique vendors with no Warning or Critical latest assessment", "eligible":"Vendors assessed by the required specialist agents", "exclusions":"Unassessed vendors", "evidence":"Latest assessment per vendor and agent", "open_records":"Current assessment state", "target":"Monitor with post-approval defect rate", "owner":"Vendor Operations", "assumption":"A vendor is Ready only when every latest specialist assessment is Pass."},
        {"name":"Needs review", "purpose":"Shows vendors requiring a governed warning decision.", "formula":"Unique vendors with at least one Warning and no Critical latest assessment", "eligible":"Assessed vendors", "exclusions":"Vendors with any Critical finding", "evidence":"Latest assessment per vendor and agent", "open_records":"Current assessment state", "target":"No fixed target", "owner":"Vendor Operations", "assumption":"Warnings do not automatically block approval but require human review."},
        {"name":"Blocked", "purpose":"Shows vendors that cannot proceed safely.", "formula":"Unique vendors with at least one Critical latest assessment", "eligible":"Assessed vendors", "exclusions":"Unassessed vendors", "evidence":"Latest assessment per vendor and agent", "open_records":"Current unresolved exposure", "target":"No arbitrary target", "owner":"Risk & Compliance", "assumption":"Multiple critical findings against one vendor still count as one blocked vendor."},
    ]
    if st.button("ⓘ How these outcomes are calculated", key="risk_metric_definitions"):
        metric_definition_dialog("Risk & Compliance", risk_definitions)
    st.markdown("### Delay drivers and next-action ownership")
    st.caption("Each vendor is assigned to one primary next-action team, so the total reconciles to the unique vendor population with current findings.")
    if not findings.empty:
        owner_risks = findings.copy()
        owner_risks["attribute"] = owner_risks["field"].map(business_field)
        owner_risks["dependency_source"] = owner_risks["field"].map(dependency_source)
        owner_risks["required_evidence"] = owner_risks["field"].map(required_evidence)
        # Roll-up findings explain underlying blockers and must not become a second owner assignment.
        owner_risks["is_rollup"] = owner_risks["field"].isin(["validation_risk", "warning_concentration"])
        has_direct_finding = owner_risks.groupby("vendor_id")["is_rollup"].transform(lambda values: (~values).any())
        assignment_candidates = owner_risks[~owner_risks["is_rollup"] | ~has_direct_finding].copy()
        assignment_candidates["severity_rank"] = assignment_candidates["severity"].map({"Critical":0, "Warning":1}).fillna(2)
        team_precedence = {"Vendor Master Data":0, "Finance":1, "Compliance":2, "Commercial":3, "Buying":4, "Vendor Onboarding":5, "Vendor Operations":6}
        assignment_candidates["team_rank"] = assignment_candidates["owner"].map(team_precedence).fillna(99)
        primary_assignment = (
            assignment_candidates.sort_values(["vendor_id", "severity_rank", "team_rank", "owner"])
            .drop_duplicates("vendor_id")[["vendor_id", "owner"]]
            .rename(columns={"owner":"primary_team"})
        )
        primary_risks = owner_risks.merge(primary_assignment, on="vendor_id", how="inner")
        primary_risks = primary_risks[primary_risks["owner"] == primary_risks["primary_team"]]
        owner_summary = primary_risks.groupby("primary_team", as_index=False).agg(
            affected_vendors=("vendor_id", "nunique"),
            attributes=("attribute", lambda values: "; ".join(sorted(set(map(str, values))))),
            dependency_sources=("dependency_source", lambda values: "; ".join(sorted(set(map(str, values))))),
            evidence=("required_evidence", lambda values: "; ".join(sorted(set(map(str, values))))),
            severity=("severity", lambda values: "Critical" if "Critical" in set(values) else "Warning"),
            required_actions=("how_to_fix", lambda values: "; ".join(dict.fromkeys(map(str, values)))),
        )
        owner_exposure = (
            primary_assignment
            .merge(vendors[["vendor_id", "planned_purchase_value"]], on="vendor_id", how="left")
            .groupby("primary_team")["planned_purchase_value"].sum()
        )
        owner_summary["commercial_exposure"] = owner_summary["primary_team"].map(owner_exposure).fillna(0)
        owner_options = ["All primary teams"] + sorted(owner_summary["primary_team"].dropna().unique().tolist())
        selected_owner = st.selectbox("Next-action team", owner_options, key="risk_owner_filter")
        show_total = selected_owner == "All primary teams"
        if not show_total:
            owner_summary = owner_summary[owner_summary["primary_team"] == selected_owner]
        owner_summary["priority_rank"] = owner_summary["severity"].map({"Critical": 0, "Warning": 1}).fillna(2)
        owner_summary = owner_summary.sort_values(["priority_rank", "commercial_exposure", "affected_vendors"], ascending=[True, False, False])
        if show_total:
            total_row = pd.DataFrame([{
                "primary_team":"TOTAL", "dependency_sources":"—", "attributes":"See team rows and downloadable vendor detail",
                "evidence":"See downloadable vendor detail", "severity":"—",
                "affected_vendors":primary_assignment["vendor_id"].nunique(),
                "commercial_exposure":primary_assignment.merge(vendors[["vendor_id","planned_purchase_value"]], on="vendor_id", how="left")["planned_purchase_value"].sum(),
                "required_actions":"—", "priority_rank":99,
            }])
            owner_summary = pd.concat([owner_summary, total_row], ignore_index=True)
        owner_summary["commercial_exposure"] = owner_summary["commercial_exposure"].map(lambda value: f"£{value:,.0f}")
        owner_summary = owner_summary.rename(columns={"primary_team":"Primary next-action team", "dependency_sources":"Dependency source", "attributes":"Missing / at-risk attributes", "evidence":"Required evidence", "severity":"Highest priority", "affected_vendors":"Unique vendors affected", "commercial_exposure":"Business value blocked", "required_actions":"Next actions"})
        st.dataframe(owner_summary[["Primary next-action team", "Dependency source", "Missing / at-risk attributes", "Highest priority", "Unique vendors affected", "Business value blocked", "Required evidence", "Next actions"]], width="stretch", hide_index=True)
        st.caption("Primary-team precedence is used only to create a non-overlapping leadership total. All secondary teams and attributes remain in the downloadable vendor action workbook.")
    st.markdown("### Intervention backlog by age")
    st.caption("Unique vendors with open findings, grouped into non-overlapping calendar-day bands.")
    delayed = findings.groupby(["vendor_id","vendor"]).agg(affected_records=("field","count"), primary_blocker=("issue","first"), required_action=("how_to_fix","first")).reset_index() if not findings.empty else pd.DataFrame()
    if not delayed.empty:
        delayed = delayed.merge(vendors[["vendor_id","source_business_unit","age_days","status"]], on="vendor_id")
        delayed = delayed[~delayed["status"].isin(["Handoff Ready","Created in System (Simulated)","Rejected"])]
        age_labels = ["0–10 days", "11–20 days", "21–30 days", "31–40 days", "41–50 days", "Over 50 days"]
        delayed["age_band"] = pd.cut(delayed["age_days"], bins=[-0.001,10,20,30,40,50,float("inf")], labels=age_labels, include_lowest=True)
        age_summary = delayed.groupby("age_band", observed=False)["vendor_id"].nunique().reindex(age_labels, fill_value=0).reset_index(name="vendors")
        age_summary["label"] = age_summary["vendors"].map(lambda value: f"{value:,}")
        age_chart = alt.Chart(age_summary).mark_bar(cornerRadiusEnd=5, color="#ff9270").encode(
            x=alt.X("vendors:Q", title="Number of vendors"),
            y=alt.Y("age_band:N", title="Age in onboarding", sort=list(reversed(age_labels))),
        )
        st.altair_chart(age_chart + age_chart.mark_text(align="left", dx=5, color="#e7edf7").encode(text="label:N"), width="stretch")
        age_definition = [{"name":"Vendors by onboarding age", "purpose":"Shows the size and severity of the unresolved onboarding backlog.", "formula":"Count of unique vendor IDs with at least one current finding, assigned to exactly one age band", "eligible":"Latest open vendor records with a valid accepted-submission timestamp and at least one current finding", "exclusions":"Vendors without findings, completed or rejected journeys, and missing timestamps", "evidence":"vendor_id, submitted_at, current findings, latest lifecycle status", "open_records":"Age equals current time minus accepted submission time", "target":"Diagnostic only until stage-level targets are approved", "owner":"Vendor Operations", "assumption":"Calendar days are used; this is total journey age, not approval waiting time."}]
        if st.button("ⓘ How aging bands are calculated", key="age_band_definitions"):
            metric_definition_dialog("Risk & Compliance", age_definition)
        nonempty_bands = age_summary.loc[age_summary["vendors"] > 0, "age_band"].astype(str).tolist()
        review_order = [label for label in reversed(age_labels) if label in nonempty_bands] or ["Over 50 days"]
        selected_age_band = st.selectbox("Age band", review_order, key="risk_age_filter")
        selected_backlog = delayed[delayed["age_band"].astype(str) == selected_age_band]
        total_value = selected_backlog["vendor_id"].drop_duplicates().map(vendors.set_index("vendor_id")["planned_purchase_value"]).sum()
        total_cols = st.columns(2)
        total_cols[0].metric("Vendors in this band", f"{selected_backlog['vendor_id'].nunique():,}")
        total_cols[1].metric("Planned value exposed", f"£{total_value:,.0f}")
    action_list = vendor_action_list()
    if not action_list.empty:
        definitions = pd.DataFrame([
            {"Field":"Vendor action list", "Definition":"One row per vendor; all missing or at-risk attributes, owners and next actions are consolidated."},
            {"Field":"Age bands", "Definition":"Calendar days since the accepted submission. Bands do not overlap; Over 50 means strictly greater than 50."},
            {"Field":"Planned value", "Definition":"Latest supplied planned purchase value. It is exposure context, not realised spend or revenue."},
        ])
        st.download_button("Download vendor action workbook (.xlsx)", workbook_bytes({"Vendor Action List":action_list, "Detailed Findings":findings.drop(columns=["priority_rank"], errors="ignore"), "Definitions":definitions}), "vendor_risk_action_list.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tabs[4]:
    st.subheader("Approval & Handoff")
    approval = vendors[vendors["status"] == "Approval Decision"].copy()
    handoff = vendors[vendors["status"] == "Handoff Ready"].copy()
    held = vendors[vendors["status"] == "On Hold"]
    summary = st.columns(3)
    summary[0].metric("Approval decisions pending", f"{len(approval):,}", help="Validation-cleared vendors waiting for a human decision.")
    summary[1].metric("Ready for simulated handoff", f"{len(handoff):,}", help="Human-approved vendors ready for payload preparation or simulated creation.")
    summary[2].metric("Cases on hold", f"{len(held):,}", help="Vendors paused by a governed human decision and awaiting resolution.")
    approval_definitions = [
        {"name":"Approval decisions pending", "purpose":"Quantifies the current human decision backlog.", "formula":"Unique latest vendor records with status Approval Decision", "eligible":"Validation-cleared vendors routed to human approval", "exclusions":"Blocked, held, rejected, and approved vendors", "evidence":"Latest lifecycle status", "open_records":"Current queue only", "target":"Measured against approval-stage SLA once timestamp evidence exists", "owner":"Approval Team", "assumption":"Queue entry means all mandatory automated checks are cleared; it does not imply automatic approval."},
        {"name":"Ready for simulated handoff", "purpose":"Shows approved vendors awaiting downstream payload preparation.", "formula":"Unique latest vendor records with status Handoff Ready", "eligible":"Human-approved vendors", "exclusions":"Vendors already marked Created in System (Simulated)", "evidence":"Governed approval event and latest lifecycle status", "open_records":"Current handoff queue only", "target":"Pending a governed handoff-stage target", "owner":"Vendor Master Data", "assumption":"This demonstration simulates handoff; production creation requires an authorised ERP integration."},
        {"name":"Cases on hold", "purpose":"Shows decisions intentionally paused pending evidence or resolution.", "formula":"Unique latest vendor records with status On Hold", "eligible":"Vendors placed on hold through a governed action", "exclusions":"All other statuses", "evidence":"Latest lifecycle status and hold audit event", "open_records":"Current holds only", "target":"No unowned or overdue holds", "owner":"Approval Team", "assumption":"A hold is not a rejection and must have an accountable resolution path."},
    ]
    if st.button("ⓘ How queue metrics are calculated", key="approval_metric_definitions"):
        metric_definition_dialog("Approval & Handoff", approval_definitions)
    st.markdown("### Approval decision SLA")
    st.caption("Working days since the vendor entered the Approval Decision queue: within target is under 12 days, 12–15 days is approaching breach, and over 15 days is overdue.")
    if not approval.empty and not audit.empty:
        approval_entries = audit[audit["to_status"].eq("Approval Decision")].copy()
        approval_entries["created_at"] = pd.to_datetime(approval_entries["created_at"], errors="coerce", utc=True)
        approval_entries = approval_entries.sort_values("created_at").groupby("vendor_id", as_index=False).tail(1)
        approval_sla = approval[["vendor_id"]].merge(approval_entries[["vendor_id","created_at"]], on="vendor_id", how="left")
        approval_sla["Working days waiting"] = approval_sla["created_at"].map(working_days_since)
        approval_sla["SLA status"] = approval_sla["Working days waiting"].map(
            lambda days: "Timestamp unavailable" if pd.isna(days) else "Within target" if days < 12 else "Approaching breach" if days <= 15 else "Overdue"
        )
        sla_order = ["Within target", "Approaching breach", "Overdue", "Timestamp unavailable"]
        sla_totals = approval_sla["SLA status"].value_counts().reindex(sla_order, fill_value=0)
        sla_cols = st.columns(4)
        for column, label in zip(sla_cols, sla_order):
            column.metric(label, f"{int(sla_totals[label]):,}")
    else:
        st.info("No vendors are currently awaiting an approval decision, so there is no active approval-SLA population.")
    st.markdown("### Queue totals by age")
    st.caption("Journey-age context only: each vendor appears once, grouped by calendar days since the accepted onboarding submission.")
    queue_age_labels = ["0–10 days", "11–20 days", "21–30 days", "31–40 days", "41–50 days", "Over 50 days"]
    queue_population = vendors[vendors["status"].isin(["Approval Decision", "Handoff Ready", "On Hold"])].copy()
    queue_population["Age band"] = pd.cut(
        queue_population["age_days"],
        bins=[-0.001,10,20,30,40,50,float("inf")],
        labels=queue_age_labels,
        include_lowest=True,
    )
    queue_age_summary = (
        queue_population.groupby(["Age band", "status"], observed=False)["vendor_id"]
        .nunique().unstack(fill_value=0).reindex(queue_age_labels, fill_value=0)
    )
    for status_name in ["Approval Decision", "Handoff Ready", "On Hold"]:
        if status_name not in queue_age_summary:
            queue_age_summary[status_name] = 0
    queue_age_summary = queue_age_summary[["Approval Decision", "Handoff Ready", "On Hold"]].reset_index()
    queue_age_summary = queue_age_summary.rename(columns={"Approval Decision":"Awaiting approval", "Handoff Ready":"Ready for handoff", "On Hold":"On hold"})
    queue_age_summary["Total"] = queue_age_summary[["Awaiting approval", "Ready for handoff", "On hold"]].sum(axis=1)
    st.dataframe(queue_age_summary, width="stretch", hide_index=True)
    if approval.empty:
        st.info("There are currently no vendors awaiting an approval decision in this test dataset. The 17 visible cases have already been approved and are waiting for simulated handoff.")
    st.markdown("### Queue lists")
    st.caption("The totals above are the leadership view. Download the case list when operational follow-up is required.")
    queue_columns = ["vendor_id","legal_name","country","strategic_tier","planned_purchase_value","age_days","status"]
    queue_book = workbook_bytes({"Approval Decisions":approval[queue_columns], "Handoff Ready":handoff[queue_columns], "On Hold":held[queue_columns]})
    st.download_button("Download approval and handoff queues (.xlsx)", queue_book, "approval_handoff_queues.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    eligible = vendors[vendors["status"].isin(["Approval Decision","On Hold","Handoff Ready"])]
    st.markdown("### Operational action workspace")
    st.caption("Open this only when an operator is ready to review one vendor and record a governed decision or simulated handoff.")
    open_workspace = st.toggle("Open vendor action workspace", value=False)
    if open_workspace and not eligible.empty:
        selected_id = st.selectbox("Select vendor", eligible["vendor_id"], format_func=lambda x: f"{x} · {eligible.set_index('vendor_id').loc[x,'legal_name']}")
        selected = eligible[eligible["vendor_id"] == selected_id].iloc[0]
        st.markdown(f"### {selected['legal_name']}")
        st.markdown(f"**{selected['status']}** · {selected.get('country','')} / {selected.get('market','')} · {selected.get('vendor_type','')} · {selected.get('strategic_tier','')} vendor")
        summary = st.columns(2)
        summary[0].metric("Planned commercial value", f"£{float(selected.get('planned_purchase_value',0)):,.0f}", help="Latest planned purchase value supplied for this vendor; no currency conversion is inferred.")
        summary[1].metric("Time in onboarding", f"{selected['age_days']:.0f} days", help="Calendar days from accepted submission timestamp to now for an open vendor.")
        selected_definitions = [
            {"name":"Planned commercial value", "purpose":"Shows the commercial dependency attached to this vendor.", "formula":"Latest supplied planned_purchase_value for the selected vendor", "eligible":"Selected vendor with a recorded value", "exclusions":"Missing values; no inferred currency conversion", "evidence":"Latest source record and value currency", "open_records":"Latest value retained", "target":"Not applicable", "owner":"Commercial Operations", "assumption":"This is planned purchase value, not guaranteed revenue or realized spend."},
            {"name":"Time in onboarding", "purpose":"Shows how long the selected vendor journey has remained open.", "formula":"Current timestamp minus accepted submitted_at timestamp", "eligible":"Open selected vendor with a valid submission timestamp", "exclusions":"Missing timestamps", "evidence":"submitted_at and latest status", "open_records":"Runs to current time while open", "target":"Diagnostic only until all stage-level targets are approved", "owner":"Vendor Operations", "assumption":"Calendar days are used; this is not approval waiting time."},
        ]
        if st.button("ⓘ How selected-vendor metrics are calculated", key="selected_vendor_metric_definitions"):
            metric_definition_dialog("Selected vendor", selected_definitions)
        st.caption(f"Downstream dependency: {selected.get('downstream_dependency','Not recorded')}")
        vendor_findings = findings[findings["vendor_id"] == selected_id] if not findings.empty else pd.DataFrame()
        if not vendor_findings.empty:
            vendor_findings = vendor_findings.copy()
            vendor_findings["Dependency source"] = vendor_findings["field"].map(dependency_source)
            vendor_findings["Required evidence"] = vendor_findings["field"].map(required_evidence)
            vendor_findings["field"] = vendor_findings["field"].map(business_field)
            vendor_findings = vendor_findings.rename(columns={"field":"Issue area","issue":"Blocking reason","severity":"Priority","owner":"Next-action team","how_to_fix":"Next action"})
            st.dataframe(vendor_findings[["Issue area","Blocking reason","Priority","Dependency source","Next-action team","Required evidence","Next action"]], width="stretch", hide_index=True)
        st.markdown("<div class='notice'>Every material decision records who acted, when, the status change, and the reason. This demonstration simulates ERP handoff; production creation requires governed approval and an authorised integration.</div>", unsafe_allow_html=True)
        actions_by_status = {
            "Approval Decision": ["Approve vendor","Request correction","Place on hold","Reject vendor"],
            "On Hold": ["Release hold","Request correction","Reject vendor"],
            "Handoff Ready": ["Prepare system-ready handoff","Mark created in system simulation"],
        }
        actions = actions_by_status.get(selected["status"], [])
        action = st.selectbox("Decision or handoff action", actions)
        action_help = {
            "Approve vendor":"Moves the vendor to Handoff Ready. It does not create an ERP record.",
            "Request correction":"Returns the vendor to Correction Required and records the requested remediation.",
            "Place on hold":"Pauses the approval decision until the stated issue is resolved.",
            "Reject vendor":"Ends this onboarding journey with a governed rejection event.",
            "Release hold":"Returns the vendor to the Approval Decision queue.",
            "Prepare system-ready handoff":"Generates a safe simulated downstream payload.",
            "Mark created in system simulation":"Closes this demonstration journey. Production creation requires an authorised ERP response and recorded ERP vendor ID.",
        }
        st.caption(action_help.get(action, ""))
        note = st.text_area("Decision note (required)")
        if st.button("Record action", type="primary", disabled=not note.strip()):
            try:
                svc.decision(selected_id, action, note.strip())
            except ValueError as error:
                st.error(str(error))
            else:
                st.success(f"{action} recorded for {selected_id}.")
                st.rerun()
        if selected["status"] == "Handoff Ready":
            st.download_button("Download simulated handoff payload", json.dumps(svc.handoff_payload(selected_id), indent=2), f"{selected_id}_handoff.json")

with tabs[5]:
    st.subheader("Audit & Data")
    st.markdown("<div class='notice'>Governance workspace: prove what changed, who decided, and how each KPI is defined. This is not another leadership dashboard.</div>", unsafe_allow_html=True)
    audited_vendors = audit["vendor_id"].nunique() if not audit.empty and "vendor_id" in audit else 0
    multi_revision = int((vendors["revision"] > 1).sum()) if "revision" in vendors else 0
    human_events = {"Vendor approved","Approve vendor","Request correction","Place on hold","Reject vendor","Release hold","Prepare system-ready handoff","Mark created in system simulation"}
    decision_vendors = audit.loc[audit["event_type"].isin(human_events), "vendor_id"].nunique() if not audit.empty else 0
    g1,g2,g3 = st.columns(3)
    g1.metric("Vendors with an audit trail", f"{audited_vendors:,}", help="Unique vendors with at least one immutable audit event.")
    g2.metric("Vendors resubmitted", f"{multi_revision:,}", help="Unique current vendor records with a stored revision number greater than one.")
    g3.metric("Vendors with human decisions", f"{decision_vendors:,}", help="Unique vendors with at least one recorded governed human decision.")
    governance_definitions = [
        {"name":"Vendors with an audit trail","purpose":"Confirms traceability coverage.","formula":"Unique vendor IDs with at least one audit event","eligible":"All active portfolio vendors","exclusions":"None","evidence":"Immutable audit events","open_records":"All events retained","target":"100% coverage","owner":"Data Governance","assumption":"An audit event proves recorded system activity, not source-document correctness."},
        {"name":"Vendors resubmitted","purpose":"Highlights journeys that required more than one accepted submission.","formula":"Unique latest vendor records where revision is greater than 1","eligible":"All active portfolio vendors","exclusions":"Rejected uploads never accepted into the portfolio","evidence":"Latest revision number","open_records":"Latest revision retained","target":"Diagnostic only","owner":"Vendor Onboarding","assumption":"Offline exchanges are not counted."},
        {"name":"Vendors with human decisions","purpose":"Shows governed human intervention coverage.","formula":"Unique vendors with a recorded approval, correction, hold, rejection, release or handoff decision event","eligible":"Vendors reaching a human decision point","exclusions":"Automated validation events","evidence":"Decision audit event and actor","open_records":"All recorded decisions retained","target":"100% of human actions recorded","owner":"Approval Team","assumption":"Only actions recorded in this workspace are counted."},
    ]
    if st.button("ⓘ How governance totals are calculated", key="audit_metric_definitions"):
        metric_definition_dialog("Audit & Data", governance_definitions)
    with st.expander("Review one vendor's audit trail"):
        selected_audit = st.selectbox("Vendor journey", vendors["vendor_id"], key="audit_vendor") if not vendors.empty else None
        if selected_audit:
            v = vendors[vendors["vendor_id"] == selected_audit].iloc[0]
            st.caption(f"Current stage: {v['status']} · Submission revision: {int(v['revision'])} · Time in onboarding: {v['age_days']:.0f} days")
            journey = pd.DataFrame(svc.repo.audit(selected_audit))
            if not journey.empty:
                journey["created_at"] = pd.to_datetime(journey["created_at"], errors="coerce", utc=True).dt.strftime("%d %b %Y %H:%M")
                journey = journey.rename(columns={"created_at":"Date","event_type":"Event","from_status":"Previous stage","to_status":"New stage","actor":"Actor","note":"Decision note"})
                st.dataframe(journey[["Date","Event","Previous stage","New stage","Actor","Decision note"]], width="stretch", hide_index=True)
    with st.expander("View KPI results and supporting evidence"):
        st.dataframe(results_frame(kpis), width="stretch", hide_index=True)
    with st.expander("View governed KPI definitions"):
        st.caption("Purpose, calculation, eligibility, exclusions, evidence, ownership, and target for each KPI.")
        st.dataframe(registry_frame(), width="stretch", hide_index=True)
    dictionary = pd.DataFrame([{"Field":c,"Definition":c.replace("_"," ").title()} for c in vendors.columns if c not in {"source_json"}])
    with st.expander("View data dictionary"): st.dataframe(dictionary, width="stretch", hide_index=True)
    st.markdown("### Governed exports")
    st.caption("Use these files for operational review, evidence checks, or downstream simulation—not as additional dashboard views.")
    c1,c2,c3 = st.columns(3)
    action_list = vendor_action_list()
    findings_book = workbook_bytes({"Vendor Action List":action_list, "Detailed Findings":findings}) if not findings.empty else b""
    c1.download_button("Vendor findings workbook", findings_book, "vendor_findings.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c2.download_button("Audit export", audit.to_csv(index=False) if not audit.empty else "", "audit_events.csv")
    handoffs = [svc.handoff_payload(v) for v in vendors.loc[vendors["status"] == "Handoff Ready", "vendor_id"]]
    c3.download_button("Simulated handoff export", json.dumps(handoffs, indent=2), "simulated_handoffs.json")
