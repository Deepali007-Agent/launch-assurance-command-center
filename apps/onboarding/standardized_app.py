"""Decision-led Vendor + Item Onboarding Intelligence interface."""
from __future__ import annotations

import hashlib
import os
import json
import sys
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from data_factory import make_dataset
from item_onboarding import sample_items, assess_items
from standalone_presentation import apply_theme, detail_table
from onboarding_intelligence import build_onboarding_intelligence
from service import VendorIQService
import importlib
import publishing
publishing = importlib.reload(publishing)
build_publication, publish, publication_state = publishing.build_publication, publishing.publish, publishing.publication_state


def _collapsed_table(*args, **kwargs):
    with st.expander("View detailed records", expanded=False):
        return st.dataframe(*args, **kwargs)


def _collapsed_download(label, *args, **kwargs):
    with st.expander(label, expanded=False):
        return st.download_button(label, *args, **kwargs)


def _collapsed_editor(*args, **kwargs):
    with st.expander("Review and update action records", expanded=False):
        return st.data_editor(*args, **kwargs)

def _csv(frame): return frame.to_csv(index=False).encode("utf-8")
def _inr(value): return f"INR {float(value):,.0f}"
def _read(upload): return pd.read_excel(upload) if Path(upload.name).suffix.lower() in {".xlsx", ".xls"} else pd.read_csv(upload)


@st.cache_resource
def _service():
    svc = VendorIQService(ROOT / "data" / "vendor_iq.db")
    if not svc.repo.vendors(): svc.ingest(make_dataset(120, "mixed"), replace=True)
    return svc


def _metric(label, value, caption, help_text):
    st.metric(label, value, help=help_text)
    st.caption(caption)


def _bar(frame, category, value, title, percent=False, color="#7f91ef"):
    data = frame.copy()
    total=pd.to_numeric(data[value],errors="coerce").sum()
    data["Label"] = data[value].map(lambda n: f"{n:.1f}%" if percent else f"{int(n):,} ({n/total:.1%})" if total else "0 (n/a)")
    scale = alt.Scale(domain=[0, 100]) if percent else alt.Scale(zero=True)
    bars = alt.Chart(data).mark_bar(color=color, cornerRadiusEnd=5).encode(
        x=alt.X(f"{category}:N", sort="-y", title=None,axis=alt.Axis(labelAngle=0,labelLimit=140)), y=alt.Y(f"{value}:Q", scale=scale, title=value), tooltip=[category, value])
    labels = alt.Chart(data).mark_text(dy=-9, color="#eef2ff", fontWeight="bold").encode(
        x=alt.X(f"{category}:N", sort="-y"), y=alt.Y(f"{value}:Q", scale=scale), text="Label:N")
    return (bars + labels).properties(title=title, height=260)


def _style():
    st.markdown("""<style>
    .stApp{background:#0b1020;color:#eef2ff}.block-container{max-width:1600px;padding-top:1.4rem}
    [data-testid="stSidebar"]{background:#11182a;border-right:1px solid #28334d}
    [data-testid="stMetric"]{background:#151d31;border:1px solid #2b3855;border-top:3px solid #7f91ef;padding:15px;border-radius:14px}
    [data-testid="stMetricLabel"]{color:#aebcdf;font-weight:700;letter-spacing:.07em;text-transform:uppercase}
    [data-testid="stMetricValue"]{color:#f8f9ff}h1,h2,h3{letter-spacing:-.025em}
    .eyebrow{color:#9fb0ff;font-size:.76rem;font-weight:800;letter-spacing:.15em;text-transform:uppercase}
    .decision{padding:17px 20px;border-radius:11px;margin:.4rem 0 1.2rem;font-size:1.02rem;font-weight:650;border-left:4px solid #ef7070;background:#3a2430}
    .decision.go{background:#19352f;border-left-color:#72d2ad}.decision.conditional{background:#3a3222;border-left-color:#efbd62}
    .flow{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:.4rem 0 1.4rem}.flow div{background:#151d31;border:1px solid #2b3855;border-radius:12px;padding:12px}.flow b{display:block;font-size:1.35rem;margin-top:5px}.flow small{color:#93a1bd}
    .stTabs [data-baseweb="tab-list"]{gap:7px;border-bottom:1px solid #303b55}.stTabs [data-baseweb="tab"]{padding:9px 15px}
    div[data-testid="stDataFrame"]{border:1px solid #2b3855;border-radius:10px}
    </style>""", unsafe_allow_html=True)


def _header(c):
    st.markdown('<div class="eyebrow">Retail Intelligence Platform · Specialist workbench</div>', unsafe_allow_html=True)
    st.title("Onboarding Intelligence")
    st.link_button("Open retail decision workspace", __import__("os").environ.get("RETAIL_APP_URL", "http://localhost:8508/"))
    st.caption("Deterministic vendor controls · governed cycle decisions in Retail Intelligence")
    st.write("Vendor approval and item onboarding evaluated together, with clear ownership, business exposure and revalidation.")


def _executive(c):
    decision = c["decision"]
    label = {"GO":"Ready", "CONDITIONAL GO":"Review", "HOLD":"Hold", "PENDING RECONCILIATION":"Review"}.get(decision, "Review")
    reason = {"GO":"Vendor and item checks are clear and identities align.", "CONDITIONAL GO":"Warnings need review before proceeding.", "HOLD":"Resolve critical vendor or item issues before proceeding.", "PENDING RECONCILIATION":"Resolve unmatched vendor IDs before proceeding."}.get(decision, "Review the source evidence.")
    if label == "Ready": st.success(f"{label} · {reason}")
    elif label == "Hold": st.error(f"{label} · {reason}")
    else: st.warning(f"{label} · {reason}")
    v, i = c["vendor"], c["item"]
    cols = st.columns(3)
    with cols[0]: _metric("Vendors ready", f"{v['ready']:,}", f"of {v['total']:,} vendors", "Vendors clear to proceed.")
    with cols[1]: _metric("Items ready", f"{i['ready']:,}", f"of {i['total']:,} items", "Items clear after vendor dependency checks.")
    with cols[2]: _metric("Records needing action", f"{v['blocked']+v['warning']+i['blocked']+i['warning']:,}", "Vendors and items", "Blocked and warning records across both sources.")
    st.subheader("Top Recommended Actions",help="Ranked corrections showing affected records, ownership and the next step.")
    actions = c["actions"]
    if actions.empty:
        st.caption("No open actions in the current assessment.")
    else:
        top = actions.sort_values(["Priority", "Records_affected"], ascending=[True, False]).head(3)
        columns = [name for name in ["Priority", "Root cause", "Records_affected", "Accountable team", "Required action"] if name in top.columns]
        st.dataframe(top[columns].rename(columns={"Records_affected":"Records impacted"}), hide_index=True, use_container_width=True)
    if label == "Hold": st.info("Next: open Actions & Recovery to review corrections, then replace the corrected source above.")
    elif label == "Review": st.info("Next: review warnings or unmatched records in the detail tabs.")
    else: st.info("Next: review and download the output contract in Audit & Data for the platform handoff.")

def _executive_details(c):
    decision = c["decision"]
    css = "go" if decision == "GO" else "conditional" if decision in {"CONDITIONAL GO","PENDING RECONCILIATION"} else ""
    reason = {"GO":"Both onboarding modules are clear and their vendor IDs reconcile.", "CONDITIONAL GO":"No critical blockers remain; warning conditions require accountable acceptance.", "HOLD":"Critical vendor or item blockers must be resolved before activation.", "PENDING RECONCILIATION":"Both modules were assessed, but unmatched vendor IDs prevent a reliable combined decision."}[decision]
    st.markdown(f'<div class="decision {css}">Onboarding readiness decision: {decision} — {reason}</div>', unsafe_allow_html=True)
    decision_frame = pd.DataFrame([
        ["Vendor Onboarding", c["vendor"]["decision"], c["vendor"]["total"], "Independent vendor assessment"],
        ["Item Onboarding", c["item"]["decision"], c["item"]["total"], "Independent item assessment"],
        ["Reconciliation", c["reconciliation"]["status"], c["reconciliation"]["linked"], f"{c['reconciliation']['coverage_pct']:.1f}% linked"],
        ["Onboarding Intelligence", decision, c["vendor"]["total"] + c["item"]["total"], "Orchestrated decision"],
    ], columns=["Decision layer","Outcome","Records assessed / linked","Interpretation"])
    _collapsed_table(decision_frame, hide_index=True, use_container_width=True)
    cols = st.columns(4)
    with cols[0]: _metric("Combined readiness", f"{c['combined_readiness']:.1f}%", "40% vendor · 60% item", "Weighted readiness = 40% vendor readiness + 60% effective item readiness. Warnings receive half credit; blockers receive none.")
    with cols[1]: _metric("Activation-ready vendors", f"{c['vendor']['ready']:,}", f"of {c['vendor']['total']:,} assessed", "Unique vendors with no critical or warning onboarding findings.")
    with cols[2]: _metric("Approval-ready items", f"{c['item']['ready']:,}", f"of {c['item']['total']:,} unique SKUs", "Unique complete SKUs whose linked vendor is clear.")
    blocked_value = _inr(c["blocked_value_inr"]) if c["value_coverage_pct"] else "Not measurable"
    with cols[3]: _metric("Business value blocked", blocked_value, f"{c['value_coverage_pct']:.1f}% INR coverage", "Planned purchase value of blocked vendors supplied in INR. If INR coverage is zero, the metric is not measurable rather than assumed to be ₹0. This is not revenue at risk.")
    left, right = st.columns(2)
    ready = pd.DataFrame({"Layer":["Vendor onboarding","Item onboarding","Combined"], "Readiness":[c["vendor"]["readiness"],c["item"]["readiness"],c["combined_readiness"]]})
    outcomes = pd.DataFrame({"Outcome":["Ready","Conditional","Blocked"], "Records":[c["vendor"]["ready"]+c["item"]["ready"],c["vendor"]["warning"]+c["item"]["warning"],c["vendor"]["blocked"]+c["item"]["blocked"]]})
    with left: st.altair_chart(_bar(ready,"Layer","Readiness","Readiness by onboarding layer",True),use_container_width=True)
    with right: st.altair_chart(_bar(outcomes,"Outcome","Records","Combined decision funnel",color="#72d2ad"),use_container_width=True)
    st.subheader("Leadership action priorities", help="Consolidated root-cause clusters ranked by urgency; not one row per record.")
    actions = c["actions"].sort_values(["Priority","Records_affected"],ascending=[True,False]).head(8) if not c["actions"].empty else c["actions"]
    _collapsed_table(actions,hide_index=True,use_container_width=True)
    _collapsed_download("Download full leadership action plan",_csv(c["actions"]),"onboarding_leadership_actions.csv","text/csv",use_container_width=True)
    st.subheader("Vendor-to-item dependency", help="Shows how vendor status propagates to linked unique SKUs.")
    _collapsed_table(c["vendor_item"].head(10),hide_index=True,use_container_width=True)
    _collapsed_download("Download complete vendor-to-item dependency",_csv(c["vendor_item"]),"vendor_item_dependency.csv","text/csv",use_container_width=True)


def _vendor(c):
    v=c["vendor"]; cols=st.columns(4)
    with cols[0]: _metric("Vendors assessed",f"{v['total']:,}","Unique vendor IDs","Count of unique vendor IDs in the latest portfolio.")
    with cols[1]: _metric("Vendor readiness",f"{v['readiness']:.1f}%","Warnings receive half credit","(Ready + 0.5 × conditional) ÷ assessed vendors.")
    with cols[2]: _metric("Blocked vendors",f"{v['blocked']:,}","Critical findings","Unique vendors with one or more critical findings.")
    with cols[3]: _metric("Items blocked by vendor",f"{c['item']['blocked_by_vendor']:,}","Downstream dependency","Unique SKUs prevented from progressing because their vendor is blocked.")
    left,right=st.columns(2)
    status=c["vendor_health"].groupby("Vendor status",as_index=False).agg(Vendors=("Vendor ID","nunique"))
    cause=c["vendor_health"].query("`Vendor status` != 'Ready'").groupby("Root cause",as_index=False).agg(Vendors=("Vendor ID","nunique")).sort_values("Vendors",ascending=False).head(8)
    with left: st.altair_chart(_bar(status,"Vendor status","Vendors","Vendor onboarding outcomes"),use_container_width=True)
    with right: st.altair_chart(_bar(cause,"Root cause","Vendors","Top vendor root causes",color="#efbd62"),use_container_width=True)
    st.subheader("Vendor decision table",help="One row per vendor, using its highest applicable severity.")
    _collapsed_table(c["vendor_health"].head(15),hide_index=True,use_container_width=True)
    _collapsed_download("Download complete vendor onboarding detail",_csv(c["vendor_health"]),"vendor_onboarding_detail.csv","text/csv",use_container_width=True)


def _item(c):
    st.info("Item onboarding = initial item setup checks: SKU identity, required fields and linked vendor readiness. Catalog = richer content quality, corrections and approval. The same SKU may appear in both datasets.")
    with st.expander("How item onboarding moves to Catalog"):
        st.write("Current flow: upload item file → validate here → download the current item source from Audit & Data → upload it to CatalogIQ → validate content → human approval / simulated ERP handoff.")
        st.caption("Connected mode sends eligible records directly to the Catalog queue. This isolated test mode does not send records. Uploading does not prove item creation or approval.")
        st.link_button("Open Catalog Intelligence", __import__("os").environ.get("CATALOG_APP_URL", "http://localhost:8507/"))
    i=c["item"]; cols=st.columns(4)
    with cols[0]: _metric("Items assessed",f"{i['total']:,}","Unique SKUs","Count after SKU deduplication.")
    with cols[1]: _metric("Item readiness",f"{i['readiness']:.1f}%","Vendor dependency applied","(Ready + 0.5 × conditional) ÷ unique SKUs after vendor dependency.")
    with cols[2]: _metric("Approval-ready items",f"{i['ready']:,}","Can progress","Complete items linked to a vendor clear to proceed.")
    with cols[3]: _metric("Items needing action",f"{i['blocked']+i['warning']:,}","Blocked plus conditional","Unique SKUs needing correction, acceptance or vendor resolution.")
    left,right=st.columns(2)
    status=c["item_health"].groupby("Effective status",as_index=False).agg(Items=("SKU","nunique"))
    affected=c["item_health"].query("`Effective status` != 'Approval ready'")
    affected=affected[~affected["Affected attributes"].fillna("").astype(str).str.strip().str.lower().isin(["none","","nan","null"])]
    cause=affected.groupby("Affected attributes",as_index=False).agg(Items=("SKU","nunique")).sort_values("Items",ascending=False).head(8)
    with left: st.altair_chart(_bar(status,"Effective status","Items","Effective item outcomes"),use_container_width=True)
    with right:
        if cause.empty: st.info("No item-attribute defects. Any remaining hold comes from vendor dependencies; review Reconciliation & Dependencies.")
        else:
            st.altair_chart(_bar(cause,"Affected attributes","Items","Top item root causes",color="#efbd62"),use_container_width=True)
            st.caption("Shows actual item-attribute defects; vendor-only holds remain in the outcome counts.")
    st.subheader("Item health summary",help="The screen shows a concise sample; the download contains every unique SKU.")
    _collapsed_table(c["item_health"].head(15),hide_index=True,use_container_width=True)
    _collapsed_download("Download complete item onboarding detail",_csv(c["item_health"]),"item_onboarding_detail.csv","text/csv",use_container_width=True)


def _reconciliation(c):
    r=c["reconciliation"]; cols=st.columns(4)
    with cols[0]: _metric("Linkage coverage",f"{r['coverage_pct']:.1f}%",f"{r['linked']:,} of {c['item']['total']:,} unique SKUs","Unique item vendor IDs found in the independently validated vendor dataset.")
    with cols[1]: _metric("Matched items",f"{r['linked']:,}","Vendor relationship confirmed","Unique SKUs whose vendor ID exists in Vendor Onboarding.")
    with cols[2]: _metric("Unmatched items",f"{r['unmatched']:,}","Reconciliation exceptions","Unique SKUs whose populated vendor ID cannot be found in the current vendor dataset.")
    with cols[3]: _metric("Items blocked by vendor",f"{c['item']['blocked_by_vendor']:,}","Valid dependency blockers","Matched unique SKUs held because the linked vendor has critical onboarding findings.")
    st.subheader("Dependency outcomes",help="Item quality and vendor quality remain separate. This table adds only the cross-dataset dependency interpretation.")
    _collapsed_table(c["vendor_item"],hide_index=True,use_container_width=True)
    unmatched=c["item_health"][c["item_health"]["Vendor onboarding status"].eq("Unmatched")]
    st.subheader("Reconciliation exceptions",help="These are cross-dataset mismatches, not ordinary item attribute defects.")
    if unmatched.empty: st.success("All populated item vendor IDs reconcile to Vendor Onboarding.")
    else: _collapsed_table(unmatched[["SKU","Product","Vendor ID","Effective status","Required action"]],hide_index=True,use_container_width=True)
    _collapsed_download("Download reconciliation exceptions",_csv(unmatched),"onboarding_reconciliation_exceptions.csv","text/csv",use_container_width=True)


def _actions(c):
    st.subheader("Actions & recovery")
    st.caption("Repeated causes are consolidated. Update progress here; revalidation regenerates the queue from the current source data.")
    if "onboarding_actions" not in st.session_state: st.session_state.onboarding_actions=c["actions"].copy()
    queue=st.session_state.onboarding_actions; statuses=queue.get("Status",pd.Series(dtype=str)); cols=st.columns(4)
    for col,label,status,caption in zip(cols,["Open actions","In progress","Ready to revalidate","Closed"],["Open","In progress","Ready to revalidate","Closed"],["Not started","Owner remediating","Evidence corrected","Verified by revalidation"]):
        with col: _metric(label,int(statuses.eq(status).sum()),caption,f"Consolidated action clusters currently marked {status}.")
    edited=_collapsed_editor(queue,hide_index=True,use_container_width=True,disabled=[x for x in queue.columns if x!="Status"],column_config={"Status":st.column_config.SelectboxColumn(options=["Open","In progress","Ready to revalidate","Closed"],required=True)},key="action_editor")
    st.session_state.onboarding_actions=edited
    a,b=st.columns(2)
    with a:
        if st.button("Revalidate current vendor and item data",type="primary",use_container_width=True):
            st.session_state.onboarding_actions=c["actions"].copy(); st.success("Revalidation completed from the latest sources."); st.rerun()
    with b: _collapsed_download("Download operational action queue",_csv(edited),"onboarding_action_queue.csv","text/csv",use_container_width=True)


def validate_onboarding_sources(svc, vendor_frame=None, item_frame=None):
    """Preflight both sources before changing either active portfolio."""
    if vendor_frame is None and item_frame is None:
        raise ValueError("Choose a vendor or item file first.")
    if vendor_frame is not None:
        accepted, rejected, errors=svc.validate_frame(vendor_frame)
        if not accepted or rejected or errors:
            reasons="; ".join(e["issue"] for e in errors)
            raise ValueError("Vendor dataset was not replaced. "+(reasons or "No data rows were found."))
    if item_frame is not None:
        item_frame=item_frame.copy()
        item_frame.columns=[str(x).strip().lower() for x in item_frame.columns]
        missing=sorted({"sku","product_name","vendor_id","brand","category","price"}-set(item_frame.columns))
        if item_frame.empty or missing:
            raise ValueError("Item dataset was not replaced. "+("Missing columns: "+", ".join(missing) if missing else "No data rows were found."))
        ids=item_frame["sku"].fillna("").astype(str).str.strip()
        if ids.eq("").any() or ids.duplicated().any():
            raise ValueError("Item dataset was not replaced. Provide unique, nonblank SKU identifiers.")
        currency_columns=[col for col in item_frame if col.lower()=="currency"]
        if currency_columns and not item_frame[currency_columns[0]].fillna("").astype(str).str.strip().str.upper().eq("INR").all():
            raise ValueError("Item prices must be in INR. Correct missing or non-INR currency values; no automatic conversion is performed.")
        assess_items(item_frame)
    if vendor_frame is not None:
        svc.ingest(vendor_frame,replace=True)
    return item_frame


def _upload_sources(svc, vendors, items):
    st.caption("Item prices use INR. If a currency column is supplied, every item must declare INR. No automatic currency conversion. Vendor commercial values are reported separately with INR coverage.")
    st.caption("Upload both files and validate once. To correct one source, upload only that file; the other source is retained.")
    left,right=st.columns(2)
    with left:
        vendor_upload=st.file_uploader("Vendor dataset",type=["csv","xlsx","xls"],key="vendor_upload",help="Required columns: vendor_id, legal_name, country and contact_email.")
        meta=st.session_state.get("vendor_source_meta",{"source":"Current portfolio","rows":len(vendors)})
        st.caption(f"Active vendor source: {meta['source']} · {meta['rows']:,} records")
    with right:
        item_upload=st.file_uploader("Item dataset",type=["csv","xlsx","xls"],key="item_upload",help="Required columns: sku, product_name, vendor_id, brand, category and price.")
        meta=st.session_state.get("item_source_meta",{"source":"Bundled sample","rows":len(items)})
        st.caption(f"Active item source: {meta['source']} · {meta['rows']:,} records")
    if st.button("Validate onboarding data",type="primary",use_container_width=True):
        try:
            incoming_vendor=_read(vendor_upload) if vendor_upload else None
            incoming_item=_read(item_upload) if item_upload else None
            with st.spinner("Checking vendor and item data…"):
                incoming_item=validate_onboarding_sources(svc,incoming_vendor,incoming_item)
            if vendor_upload:
                st.session_state.vendor_source_meta={"source":vendor_upload.name,"rows":len(incoming_vendor)}
            if incoming_item is not None:
                st.session_state.item_onboarding_data=incoming_item
                st.session_state.item_source_meta={"source":item_upload.name,"rows":len(incoming_item)}
            st.session_state.pop("onboarding_actions",None)
            st.session_state.pop("onboarding_evaluation",None)
            st.session_state.onboarding_validation_notice="Validation complete. Vendor and item results are available in their respective tabs."
            st.rerun()
        except (ValueError,TypeError,OSError,KeyError) as exc:
            st.error(str(exc))


def _audit(svc,vendors,items,c):
    st.subheader('Audit & Data')
    st.caption('Review evaluated sources, decision evidence and downloads. Use Upload onboarding data above to replace a source.')
    stable_vendors=vendors.drop(columns=["age_days"],errors="ignore")
    fingerprint=hashlib.sha256((stable_vendors.to_json(date_format="iso",orient="split")+items.to_json(date_format="iso",orient="split")).encode()).hexdigest()
    stamp=st.session_state.get("onboarding_evaluation")
    if not stamp or stamp["fingerprint"]!=fingerprint:
        stamp={"fingerprint":fingerprint,"run_id":"ONB-"+uuid4().hex[:10].upper(),"evaluated_at":datetime.now(timezone.utc)}
        st.session_state.onboarding_evaluation=stamp
    run_id=stamp["run_id"]; cols=st.columns(3)
    with cols[0]: _metric("Assessment reference (Run ID)",run_id,"Reference for this evaluation; use it to match results and exports.","A unique reference for one evaluation of the vendor and item data; it is not a vendor or SKU ID.")
    evaluated_local=stamp["evaluated_at"].astimezone(timezone(timedelta(hours=5,minutes=30)))
    with cols[1]: _metric("Evaluated at",evaluated_local.strftime("%d-%m-%y %H:%M:%S IST"),"Last evaluation time · India Standard Time","When these results were evaluated; browsing tabs does not change this time.")
    with cols[2]: _metric("Decision",c["decision"],"Governed outcome","HOLD for critical blockers, CONDITIONAL GO for warnings, otherwise GO.")
    payload={"schema_version":"onboarding-intelligence.v1","run_id":run_id,"evaluated_at":stamp["evaluated_at"].isoformat(),"decision":c["decision"],"combined_readiness_pct":c["combined_readiness"],"vendor":c["vendor"],"item":c["item"],"blocked_value_inr":c["blocked_value_inr"]}
    _collapsed_download("Download parent-platform output contract",json.dumps(payload,indent=2),f"{run_id}_output_contract.json","application/json",use_container_width=True)
    with st.expander("Definitions, assumptions and calculation contract"):
        st.markdown("""- **Unique counts:** vendor ID and SKU are deduplicated.
        - **Highest severity:** Critical overrides Warning, which overrides None.
        - **Readiness:** ready = 1.0, warning/conditional = 0.5, blocked = 0.
        - **Combined readiness:** 40% vendor + 60% effective item readiness.
        - **Dependency:** an item cannot be ready while its linked vendor is blocked or conditional.
        - **Business value blocked:** planned purchase value of blocked vendors explicitly in INR; not revenue at risk.
        - **Decision:** HOLD for any critical blocker; CONDITIONAL GO for warning-only exposure; otherwise GO.""")
    with st.expander("Source downloads"):
        _collapsed_download("Download current vendor source",_csv(vendors),"current_vendor_source.csv","text/csv",use_container_width=True)
        _collapsed_download("Download current item source",_csv(items),"current_item_source.csv","text/csv",use_container_width=True)


def _publish_results(svc, vendors, assessments):
    st.subheader("Publish to Retail Intelligence",help="Send assessed vendor evidence to the shared decision workspace.")
    st.caption("Send the current vendor assessment. Retail Intelligence combines it with item results published by CatalogIQ and buying results published by PO Intelligence.")
    payload = build_publication(vendors, assessments, svc.kpis())
    configured = bool(os.getenv("RETAIL_INTELLIGENCE_API_URL") and os.getenv("RETAIL_INTELLIGENCE_API_TOKEN") and payload.get("business_cycle_id"))
    if not configured:
        st.warning("Publishing is not configured. Start the apps using the connected launcher.")
    if st.button("Publish to Retail Intelligence", type="primary", disabled=not configured or vendors.empty):
        try:
            with st.spinner("Sending assessed vendor results…"):
                state = publish(payload)
            st.session_state.pop("vendor_publish_error", None)
            st.success("Retail Intelligence accepted the vendor results.")
        except Exception as exc:
            st.session_state.vendor_publish_error = f"Publication failed: {exc}"
    if st.session_state.get("vendor_publish_error"):
        st.error(st.session_state.vendor_publish_error)
    state = publication_state(payload)
    if state.get("status") == "Published":
        st.caption("Acknowledged · current vendor assessment received by Retail Intelligence")
        with st.expander("Publication receipt"):
            st.json(state.get("acknowledgement", {}))


def render_app():
    st.set_page_config(page_title="Onboarding Intelligence",page_icon="◈",layout="wide"); _style(); apply_theme()
    from workflow_connection import workflow
    importlib.reload(workflow)
    testing=st.toggle('Standalone testing mode',value=False,help='Test source rules in isolation; this mode does not hand records to the connected workflow.')
    if not testing:
        from retail_workflow import stages
        importlib.reload(stages).onboarding(sys.modules[__name__]);return
    st.warning('Standalone test portfolio: results here do not update shared workflow requests.')
    svc=_service()
    vendors,assessments,_=svc.snapshot()
    if "item_onboarding_data" not in st.session_state: st.session_state.item_onboarding_data=sample_items()
    items=st.session_state.item_onboarding_data; c=build_onboarding_intelligence(vendors,assessments,items); _header(c)
    if st.session_state.get('onboarding_validation_notice'): st.success(st.session_state.pop('onboarding_validation_notice'))
    with st.expander('Upload or replace data', expanded=True):
        _upload_sources(svc, vendors, items)
    tabs=st.tabs(["Dashboard","Vendor Onboarding","Item Onboarding","Reconciliation & Dependencies","Actions & Recovery","Audit & Data"])
    with tabs[0]:
        _executive(c)
        _publish_results(svc, vendors, assessments)
    with tabs[1]: _vendor(c)
    with tabs[2]: _item(c)
    with tabs[3]: _reconciliation(c)
    with tabs[4]: _actions(c)
    with tabs[5]:
        _audit(svc,vendors,items,c)
        with st.expander('Detailed assessment and charts'):
            _executive_details(c)
