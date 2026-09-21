"""Shared standalone presentation contract, version 2026-09-19."""
import hashlib
import json
import subprocess
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from portable_excel import excel_bytes


def frame_records(frame):
    return json.loads(pd.DataFrame(frame).to_json(orient="records",date_format="iso"))

@st.fragment
def export_workbook(sheets, name, context=None):
    payload={label:frame_records(data) for label,data in sheets.items()}
    if context: payload["Run context"]=[{"Field":k,"Value":str(v)} for k,v in context.items()]
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:16]
    key="xlsx_"+name+digest
    if st.button("Prepare Excel",key="prepare_"+key,help="Build a workbook containing every record in this section."):
        try:
            with st.spinner("Preparing Excel…"):
                st.session_state[key]=excel_bytes(payload)
        except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
            st.error(f"Excel could not be prepared: {exc}. Retry preparation.")
    if key in st.session_state:
        st.download_button("Download Excel",st.session_state[key],name+".xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_"+key,on_click="ignore")

def detail_table(frame, title, key, context=None):
    frame=pd.DataFrame(frame)
    with st.expander(f"{title} · {len(frame):,} records · Excel",expanded=False):
        st.dataframe(frame,width="stretch",hide_index=True,height=min(420, max(120, 36*(len(frame)+1))))
        export_workbook({"Records":frame},key,context)

def apply_theme():
    st.markdown("""<style>
    .stApp{background:#0b1020;color:#e8edf7}
    .stApp, .stApp h1, .stApp h2, .stApp h3, .stApp p, .stApp label,
    .stApp button, .stApp input, .stApp textarea, .kpi-cell, .kpi-cell *,
    .exec-banner, .exec-banner *, .sec-hdr, .data-contract, .data-contract *,
    .metric-card, .metric-card *, .workflow-strip, .workflow-strip *
    {font-family:"Source Sans 3","Source Sans Pro",Arial,sans-serif!important}
    .block-container{max-width:1440px;padding-top:1.6rem;padding-bottom:3rem}
    h1{font-size:2.25rem!important;letter-spacing:-.035em}
    h2,h3{letter-spacing:-.02em}
    [data-testid="stTabs"] [data-baseweb="tab-list"]{gap:.25rem;background:#11182a;padding:.35rem;border-radius:12px}
    [data-testid="stTabs"] [data-baseweb="tab"]{height:42px;border-radius:9px;padding:0 .9rem;color:#aeb9cb}
    [data-testid="stTabs"] [aria-selected="true"]{background:#243054;color:#fff!important}
    [data-testid="stTabs"] [data-baseweb="tab-highlight"]{display:none}
    div.stButton>button[kind="primary"]{background:#657cf4;border-color:#657cf4;color:white;border-radius:10px;font-weight:700}
    div.stButton>button{border-radius:10px;min-height:44px}
    [data-testid="stFileUploader"]{border:1px dashed #405073;border-radius:12px;padding:.3rem;background:#10182a}
    [data-testid="stDataFrame"]{border:1px solid #26314a;border-radius:12px;overflow:hidden}
    .kpi-cell .val{font-size:2rem;font-weight:750}
    </style>""",unsafe_allow_html=True)
    definitions={
      "Executive Summary":"The current decision, its business impact and the next actions to take.",
      "Executive Dashboard":"The current decision, its business impact and the next actions to take.",
      "Vendor Onboarding":"Vendor information and approval checks required before buying.",
      "Item Onboarding":"Product information checks and linked vendor dependencies.",
      "Reconciliation & Dependencies":"Items linked to vendors and the prerequisites holding them back.",
      "Actions & Recovery":"Corrections, accountable owners and progress toward readiness.",
      "Audit & Data":"Source records, calculation definitions and downloadable evidence.",
      "Submission & SLA":"Submission defects and delivery windows requiring attention.",
      "Vendor Intelligence":"Vendor-level risk and the corrections with the greatest impact.",
      "Decision & Export":"Supporting recommendations and the full downloadable assessment.",
      "Catalog Health":"Product completeness and quality issues affecting catalog readiness.",
      "Division Performance":"Compare readiness and commercial exposure by division.",
      "Revenue & Customer Impact":"Estimated business exposure and customer-content risks.",
      "Top Recommended Actions":"Ranked corrections showing what to fix next and why.",
      "Upload or replace data":"Choose source files, then validate to refresh this assessment.",
      "Publish to Retail Intelligence":"Send validated evidence to the shared decision workspace; this does not approve release.",
      "CatalogIQ Pro":"Evaluate product data quality before catalog approval and handoff.",
      "Onboarding Intelligence":"Evaluate vendor and item inputs together before buying.",
      "PO / Buying Intelligence":"Evaluate purchase-order lines and commercial buying requirements.",
      "Top Submission Risks":"Most frequent validation defects and their affected line counts.",
      "SLA Compliance":"Delivery windows compared with the configured timing requirements.",
      "Leadership Decision Queue":"PO-level recommendations based on the latest line assessments.",
      "Vendor Risk Scorecard":"Vendor-level error rates, exposure and readiness findings.",
      "Division Performance Analysis":"Buying quality and commercial measures grouped by division.",
      "Pattern Intelligence":"Recurring issues that suggest a broader process correction.",
      "Executive AI Insights":"Rule-based insights with optional generated explanations.",
      "Export Executive Report":"Download the summary and all assessed records in one workbook.",
      "Executive Command Center":"Summary measures supporting the current buying recommendation.",
      "Business Impact Summary":"Commercial exposure and modeled process benefits for this run.",
    }
    definitions.update({'Platform Workflow': 'The sequence from file intake through validation to evidence publication.', 'Optional explanations': 'Optional generated narratives supplement the deterministic checks.', 'From buysheet to release readiness': 'Validate buying requirements before publishing evidence for review.', 'Synthetic portfolio environment': 'A demonstration portfolio with simulated ERP handoffs.', 'Financial Impact Assessment': 'Calculated portfolio value and modeled process benefits for this run.', 'Priority view': 'Compare the largest sources of catalog risk by vendor, division or cause.', 'Leadership action plan': 'Ranked corrective actions and the accountable operational teams.', 'Operations Summary': 'Current catalog workflow stages, blockers and turnaround measures.', 'Information Quality': 'Missing or invalid product attributes requiring correction.', 'Human Approval & ERP Handoff': 'Human review and simulated transfer of eligible item records.', 'Revenue exposure by severity': 'Share of measured at-risk value associated with each severity.', 'Customer risk by division': 'Average content-related customer risk by product division.', 'View detailed records': 'Inspect the underlying records supporting this summary.', 'Publication receipt': 'The receiver acknowledgement for the published source evidence.', 'Source downloads': 'Download the current vendor and item inputs for this assessment.', 'Detailed assessment and charts': 'Supporting readiness measures, distributions and action evidence.'})
    components.html("""<script>
    const defs="""+json.dumps(definitions)+""";const doc=window.parent.document;
    function apply(){doc.querySelectorAll('h1,h2,h3,h4,[role="tab"],summary p,.sec-hdr,.hero-title,.po-hero-title').forEach(el=>{
      const label=el.textContent.trim();
      const definition=defs[label] || (label.includes('· Excel')?'Inspect all records and prepare a complete Excel download.':null);
      if(definition){el.title=definition;el.setAttribute('aria-description',definition);}
    });}apply();
    if(window.parent.standaloneObserver)window.parent.standaloneObserver.disconnect();
    window.parent.standaloneObserver=new MutationObserver(apply);
    window.parent.standaloneObserver.observe(doc.body,{childList:true,subtree:true});
    </script>""",height=0)
