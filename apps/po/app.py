import streamlit as st
import pandas as pd
from datetime import datetime
import html
import io
import sqlite3
import hashlib
import os
from standalone_presentation import apply_theme, detail_table, export_workbook
from ui.decision_charts import outcome_rows, issue_rows, exposure_rows, bar_chart


st.set_page_config(page_title="PO / Buying Intelligence", page_icon="◈", layout="wide")
import importlib
from agents import executive_agent as executive_module
analyze_executive_decision = importlib.reload(executive_module).analyze_executive_decision
from domain.assessment_mapper import results_to_assessments
from domain.contracts import RunMetadata
from domain.input_pipeline import REQUIRED_COLUMNS, validate_upload
from domain.repository import AssessmentRepository
import importlib
from domain import publishing as publication_module
publication_module = importlib.reload(publication_module)
build_publication = publication_module.build_publication
publish = publication_module.publish
publication_state = publication_module.publication_state
from services.llm_service import ask_llm
from ui.platform_shell import (
    PLATFORM_CSS,
    render_workflow,
)


def render_po_run_contract(metadata: RunMetadata) -> None:
    """Render PO run metadata without relying on a hot-reloaded module symbol."""
    st.markdown(
        f"""
        <div class="data-contract">
          <div class="contract-cell">
            <div class="label">Validation Run</div>
            <div class="value">{html.escape(metadata.run_id)}</div>
          </div>
          <div class="contract-cell">
            <div class="label">Rows</div>
            <div class="value">{metadata.row_count:,}</div>
          </div>
          <div class="contract-cell">
            <div class="label">Source File</div>
            <div class="value">{html.escape(metadata.source_file)}</div>
          </div>
          <div class="contract-cell">
            <div class="label">Module</div>
            <div class="value">PO Intelligence</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


st.markdown("""
<style>

:root {
    --bg:#0E1117; --surface:#262730; --surface2:#1B1F2A;
    --border:#3A3F4B; --border2:#4B5260;
    --ink:#FAFAFA; --ink2:#D7DAE0; --ink3:#A0A6B2;
    --green:#4CC38A; --green-bg:#123524; --green-border:#286447;
    --amber:#FFB454; --amber-bg:#3A2A12; --amber-border:#805B24;
    --red:#FF6B6B; --red-bg:#3B1C1C; --red-border:#7D3737;
    --blue:#79A8FF; --blue-bg:#172554; --blue-border:#35569A;
    --purple:#C39BFF; --purple-bg:#2F2046;
}

html,body,[class*="css"]{font-family:Arial,sans-serif;background:var(--bg);color:var(--ink);}
.main,[data-testid="stAppViewContainer"]{background:var(--bg);}
[data-testid="stHeader"]{background:var(--bg);border-bottom:1px solid var(--border);}
[data-testid="stSidebar"]{background:var(--surface);border-right:1px solid var(--border);}

/* ── Platform Header ── */
.platform-header{
    background:var(--ink); color:#fff;
    padding:28px 36px; border-radius:6px;
    margin-bottom:20px; display:flex;
    justify-content:space-between; align-items:center;
}
.platform-header h1{
    font-family:Arial,sans-serif; font-weight:800;
    font-size:1.6rem; color:#fff; margin:0 0 3px 0; letter-spacing:-0.3px;
}
.platform-header p{color:#9A9890;font-size:0.82rem;margin:0;}
.platform-meta{text-align:right;}
.platform-meta .version{
    font-family:Arial,sans-serif; font-size:0.68rem;
    color:#9A9890; letter-spacing:1px;
}

/* ── Executive Alert Banner ── */
.exec-banner{
    border-radius:4px; padding:14px 20px;
    margin-bottom:8px; display:flex;
    align-items:flex-start; gap:12px;
}
.exec-banner.critical{background:var(--red-bg);border:1px solid var(--red-border);}
.exec-banner.warning{background:var(--amber-bg);border:1px solid var(--amber-border);}
.exec-banner.positive{background:var(--green-bg);border:1px solid var(--green-border);}
.exec-banner.info{background:var(--blue-bg);border:1px solid var(--blue-border);}
.exec-banner .icon{font-size:1rem;margin-top:1px;flex-shrink:0;}
.exec-banner .content .title{font-weight:600;font-size:0.85rem;margin-bottom:2px;}
.exec-banner.critical .content .title{color:var(--red);}
.exec-banner.warning .content .title{color:var(--amber);}
.exec-banner.positive .content .title{color:var(--green);}
.exec-banner.info .content .title{color:var(--blue);}
.exec-banner .content .detail{font-size:0.78rem;color:var(--ink2);}

/* ── Section Header ── */
.sec-hdr{
    font-family:Arial,sans-serif; font-weight:700;
    font-size:0.68rem; text-transform:uppercase;
    letter-spacing:2px; color:var(--ink3);
    padding:20px 0 10px; border-bottom:1px solid var(--border);
    margin-bottom:14px;
}

/* ── KPI Grid ── */
.kpi-grid{
    display:grid; gap:1px;
    background:var(--border);
    border:1px solid var(--border);
    border-radius:4px; overflow:hidden;
}
.kpi-cell{
    background:var(--surface);
    padding:18px 22px;
}
.kpi-cell .lbl{
    font-size:0.67rem; text-transform:uppercase;
    letter-spacing:1.5px; color:var(--ink3);
    margin-bottom:6px; font-weight:500;
}
.kpi-cell .val{
    font-family:Arial,sans-serif; font-weight:800;
    font-size:1.8rem; line-height:1; color:var(--ink);
}
.kpi-cell .sub{
    font-family:Arial,sans-serif;
    font-size:0.68rem; color:var(--ink3); margin-top:4px;
}
.kpi-cell .trend-up{color:var(--red);font-size:0.72rem;}
.kpi-cell .trend-dn{color:var(--green);font-size:0.72rem;}
.kpi-cell .trend-ok{color:var(--green);font-size:0.72rem;}
.c-green .val{color:var(--green);}
.c-amber .val{color:var(--amber);}
.c-red   .val{color:var(--red);}
.c-blue  .val{color:var(--blue);}
.c-purple .val{color:var(--purple);}

/* ── Data Table ── */
.data-table{width:100%;border-collapse:collapse;font-size:0.83rem;}
.data-table thead tr{border-bottom:2px solid var(--ink);}
.data-table th{
    font-family:Arial,sans-serif; font-weight:700;
    font-size:0.65rem; text-transform:uppercase;
    letter-spacing:1.5px; color:var(--ink2);
    padding:10px 14px; text-align:left; white-space:nowrap;
}
.data-table td{
    padding:11px 14px; border-bottom:1px solid var(--border);
    color:var(--ink); vertical-align:middle;
}
.data-table tr:last-child td{border-bottom:none;}
.data-table tr:hover td{background:var(--surface2);}
.mono{font-family:Arial,sans-serif;font-size:0.8rem;}
.tbl-wrap{
    background:var(--surface); border:1px solid var(--border);
    border-radius:4px; overflow:hidden;
}

/* ── Pills ── */
.pill{
    display:inline-block; font-family:Arial,sans-serif;
    font-size:0.65rem; font-weight:500; letter-spacing:0.5px;
    padding:2px 9px; border-radius:2px; white-space:nowrap;
}
.p-pass{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border);}
.p-warn{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber-border);}
.p-fail{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border);}
.p-a{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border);}
.p-b{background:#EBF5EF;color:#2A6B44;border:1px solid #B8D8C4;}
.p-c{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber-border);}
.p-d{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border);}
.p-high{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border);}
.p-medium{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber-border);}
.p-low{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border);}
.p-critical{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border);}
.p-action{background:var(--purple-bg);color:var(--purple);border:1px solid #C8A8E8;}

/* ── Progress bar ── */
.pb{background:var(--border);border-radius:2px;height:5px;overflow:hidden;}
.pb-fill{height:5px;border-radius:2px;}

/* ── Timeline ── */
.tl-row{display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);}
.tl-month{width:65px;font-family:Arial,sans-serif;font-size:0.72rem;color:var(--ink3);text-align:right;flex-shrink:0;}
.tl-wrap{flex:1;background:var(--border);border-radius:2px;height:22px;display:flex;overflow:hidden;}
.tl-clean{background:var(--ink);height:22px;display:flex;align-items:center;padding-left:6px;min-width:0;}
.tl-flag{background:#C0392B;height:22px;display:flex;align-items:center;padding-left:4px;min-width:0;}
.tl-lbl{font-size:0.65rem;color:#fff;white-space:nowrap;overflow:hidden;font-family:Arial,sans-serif;}
.tl-meta{width:180px;text-align:right;font-family:Arial,sans-serif;font-size:0.7rem;color:var(--ink3);flex-shrink:0;}

/* ── Readiness Card ── */
.ready-card{
    background:var(--surface);border:1px solid var(--border);
    border-radius:4px;padding:14px 18px;margin-bottom:6px;
}
.ready-po{font-family:Arial,sans-serif;font-size:0.72rem;color:var(--ink3);margin-bottom:5px;}
.ready-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;}
.ready-score{font-family:Arial,sans-serif;font-weight:800;font-size:1.5rem;}
.ready-meta{font-family:Arial,sans-serif;font-size:0.68rem;color:var(--ink3);display:flex;justify-content:space-between;margin-top:5px;}

/* ── Issue Cards ── */
.iss{padding:9px 12px;margin-bottom:3px;border-radius:3px;font-size:0.83rem;border-left:3px solid;}
.iss-e{background:var(--red-bg);border-color:var(--red);}
.iss-w{background:var(--amber-bg);border-color:var(--amber);}
.iss-ai{background:var(--green-bg);border-color:var(--green);margin-top:6px;}
.iss-lbl{font-family:Arial,sans-serif;font-size:0.62rem;font-weight:500;letter-spacing:0.5px;margin-bottom:2px;color:var(--ink2);}

/* ── Action Card ── */
.action-card{
    background:var(--surface);border:1px solid var(--border);
    border-radius:4px;padding:14px 18px;margin-bottom:6px;
    display:flex;gap:14px;align-items:flex-start;
}
.action-num{
    background:var(--ink);color:#fff;
    font-family:Arial,sans-serif;font-weight:800;
    font-size:0.9rem;width:26px;height:26px;
    border-radius:3px;display:flex;align-items:center;
    justify-content:center;flex-shrink:0;
}
.action-body .action-title{font-weight:600;font-size:0.87rem;color:var(--ink);margin-bottom:3px;}
.action-body .action-detail{font-size:0.78rem;color:var(--ink2);}
.action-body .action-impact{
    font-family:Arial,sans-serif;font-size:0.7rem;
    color:var(--red);margin-top:4px;
}

/* ── Error Type Row ── */
.err-row{
    display:flex;align-items:center;gap:12px;
    padding:10px 0;border-bottom:1px solid var(--border);
}
.err-name{width:200px;font-size:0.83rem;font-weight:500;flex-shrink:0;}
.err-bar-wrap{flex:1;}
.err-count{width:50px;text-align:right;font-family:Arial,sans-serif;font-size:0.8rem;flex-shrink:0;}
.err-pct{width:45px;text-align:right;font-family:Arial,sans-serif;font-size:0.8rem;color:var(--ink3);flex-shrink:0;}
.err-cost{width:100px;text-align:right;font-family:Arial,sans-serif;font-size:0.78rem;color:var(--red);flex-shrink:0;}
.err-sev{width:80px;text-align:right;flex-shrink:0;}

/* Buttons */
.stButton>button{
    background:var(--ink);color:#fff;border:none;border-radius:3px;
    padding:10px 28px;font-family:Arial,sans-serif;font-weight:700;
    font-size:0.85rem;letter-spacing:0.3px;width:100%;
}

/* ── Priority Badge ── */
.pri-badge{
    display:inline-flex;align-items:center;justify-content:center;
    width:22px;height:22px;border-radius:3px;
    font-family:Arial,sans-serif;font-weight:800;font-size:0.75rem;
    color:#fff;flex-shrink:0;
}
.pri-1{background:var(--red);}
.pri-2{background:var(--amber);}
.pri-3{background:var(--blue);}
.pri-4{background:var(--ink2);}
.pri-5{background:var(--green);}

/* ── Decision Card ── */
.decision-card{
    background:var(--surface);border:1px solid var(--border);
    border-radius:4px;padding:16px 20px;margin-bottom:6px;
}
.decision-po{font-family:Arial,sans-serif;font-size:0.75rem;color:var(--ink3);margin-bottom:8px;}
.decision-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:8px;}
.decision-option{padding:10px 12px;border-radius:3px;border:1px solid var(--border);}
.decision-option.hold{background:var(--amber-bg);border-color:var(--amber-border);}
.decision-option.submit{background:var(--red-bg);border-color:var(--red-border);}
.decision-option.recommended{background:var(--green-bg);border-color:var(--green-border);}
.decision-option .opt-label{font-family:Arial,sans-serif;font-weight:700;font-size:0.65rem;text-transform:uppercase;letter-spacing:1px;margin-bottom:4px;}
.decision-option.hold .opt-label{color:var(--amber);}
.decision-option.submit .opt-label{color:var(--red);}
.decision-option.recommended .opt-label{color:var(--green);}
.decision-option .opt-detail{font-size:0.78rem;color:var(--ink2);}

/* ── Pattern Card ── */
.pattern-card{
    background:var(--surface);border:1px solid var(--border);
    border-radius:4px;padding:14px 18px;margin-bottom:6px;
    display:flex;gap:12px;align-items:flex-start;
}
.pattern-icon{font-size:1.1rem;flex-shrink:0;margin-top:1px;}
.pattern-body .pattern-title{font-weight:600;font-size:0.85rem;color:var(--ink);margin-bottom:3px;}
.pattern-body .pattern-detail{font-size:0.78rem;color:var(--ink2);}
.pattern-body .pattern-signal{font-family:Arial,sans-serif;font-size:0.7rem;color:var(--blue);margin-top:3px;}

/* ── Tradeoff Table ── */
.tradeoff-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px;}
.tradeoff-cell{background:var(--surface2);border:1px solid var(--border);border-radius:3px;padding:12px 14px;}
.tradeoff-cell .tc-label{font-family:Arial,sans-serif;font-weight:700;font-size:0.65rem;text-transform:uppercase;letter-spacing:1px;color:var(--ink3);margin-bottom:6px;}
.tradeoff-cell .tc-value{font-family:Arial,sans-serif;font-size:0.82rem;color:var(--ink);}

div[data-testid="stFileUploader"]{background:var(--surface);border:1px solid var(--border);border-radius:4px;}
details{border:1px solid var(--border)!important;border-radius:4px!important;margin-bottom:3px;background:var(--surface);}
p,li,span{color:var(--ink);}
</style>
""", unsafe_allow_html=True)
st.markdown(PLATFORM_CSS, unsafe_allow_html=True)

# ── Constants ─────────────────────────────────────────────────────────────────
MANDATORY_FIELDS = REQUIRED_COLUMNS
VALID_DIVISIONS = {"Accessories","Menswear","Womenswear","Kids"}
VALID_LOCATIONS = {"NJ","TX","NY","LA","CA","IL","FL"}
DIV_SUB = {
    "Menswear":   {"Jackets","Shirts","Pants","Suits","Shorts"},
    "Womenswear": {"Jackets","Shirts","Pants","Dresses","Skirts","Shorts"},
    "Kids":       {"Jackets","Shirts","Pants","Dresses","Shorts"},
    "Accessories":{"Bags","Belts","Hats","Scarves","Jewelry","Jackets","Pants","Shirts","Dresses"},
}
ANALYST_RATE    = 15    # INR  per hour — GCC blended rate
BATCH_RUN_HRS   = 2.5   # hours per wasted batch run
REWORK_MINS     = 45    # minutes per flagged row rework
RUNS_PER_MONTH  = 20    # typical GCC monthly run frequency

# ── Helpers ───────────────────────────────────────────────────────────────────
def parse_date(val):
    for fmt in ("%d-%m-%Y","%Y-%m-%d","%m/%d/%Y","%d/%m/%Y"):
        try: return datetime.strptime(str(val).strip(), fmt)
        except (TypeError, ValueError): continue
    return None

def get_risk(e,w):
    if len(e)>=2:   return "HIGH"
    if len(e)==1:   return "MEDIUM"
    if len(w)>=2:   return "MEDIUM"
    if len(w)==1:   return "LOW"
    return "CLEAR"

def readiness(e,w): return max(0,100-len(e)*25-len(w)*10)

def vendor_grade(er):
    if er==0:    return "A","p-a"
    if er<=25:   return "B","p-b"
    if er<=60:   return "C","p-c"
    return "D","p-d"

def rc(s):
    if s>=80: return "var(--green)"
    if s>=50: return "var(--amber)"
    return "var(--red)"

def rl(s):
    if s>=80: return "✓ Clear"
    if s>=50: return "⚠ Review"
    return "✕ Hold"

def rpill(s):
    if s>=80: return "p-pass"
    if s>=50: return "p-warn"
    return "p-fail"

# ── Validate Row ──────────────────────────────────────────────────────────────
def validate_row(row, idx):
    errors,warnings = [],[]
    error_types = []
    label = f"{row.get('PO_ID','?')} · {row.get('Vendor ID','?')} · {row.get('Vendor Name','?')}"

    # Mandatory fields
    missing = []
    for f in MANDATORY_FIELDS:
        v = row.get(f,None)
        if pd.isna(v) or str(v).strip()=="":
            errors.append(f"<b>{f}</b> is missing")
            missing.append(f)
    if missing: error_types.append("Missing Fields")

    # Division
    division  = str(row.get("Division","")).strip()
    sub_class = str(row.get("Sub-Class","")).strip()
    if division and division not in VALID_DIVISIONS:
        errors.append(f"Unknown Division: <b>{division}</b>")
        error_types.append("Invalid Division")
    if division in DIV_SUB and sub_class and sub_class not in DIV_SUB[division]:
        warnings.append(f"Sub-Class <b>{sub_class}</b> unusual for <b>{division}</b>")
        error_types.append("Sub-Class Mismatch")

    # Financials
    cost=retail=orig_retail=0; revenue=margin_gap=cost_val=0.0; margin_pct=None
    try:
        cost        = float(row.get("Cost",0))
        retail      = float(row.get("Reg Retail",0))
        orig_retail = float(row.get("Original Retail",retail))
        qty         = int(row.get("Total Quantity",0))
        revenue     = retail*qty
        cost_val    = cost*qty
        if cost>0 and retail>0:
            margin_pct=(retail-cost)/retail*100
            if margin_pct<45:
                margin_gap=(0.45*retail-(retail-cost))*qty
                warnings.append(f"Margin <b>{margin_pct:.1f}%</b> below 45% floor (Cost INR {cost:.2f} · Retail INR {retail:.2f})")
                error_types.append("Low Margin")
        if orig_retail<retail:
            warnings.append(f"Original Retail INR {orig_retail:.2f} < Reg Retail INR {retail:.2f}")
            error_types.append("Retail Discrepancy")
    except (TypeError, ValueError): errors.append("Cost/Retail/Quantity non-numeric"); error_types.append("Data Error")

    # Dates
    ship_raw = row.get("Ship Dates", "")
    cancel_raw = row.get("Cancel Dates", "")
    ship_dt = parse_date(ship_raw)
    cancel_dt = parse_date(cancel_raw)
    if not pd.isna(ship_raw) and str(ship_raw).strip() and ship_dt is None:
        errors.append("Ship Date has an invalid format")
        error_types.append("Data Error")
    if not pd.isna(cancel_raw) and str(cancel_raw).strip() and cancel_dt is None:
        errors.append("Cancel Date has an invalid format")
        error_types.append("Data Error")
    ship_month = ship_dt.strftime("%Y-%m") if ship_dt else None
    window_days = None
    if ship_dt and cancel_dt:
        window_days=(cancel_dt-ship_dt).days
        if window_days<0:
            errors.append("Cancel Date <b>before</b> Ship Date — critical scheduling error")
            error_types.append("Cancel Before Ship")
        elif window_days<14:
            warnings.append(f"Fulfilment window <b>{window_days} days</b> — below 14-day SLA minimum")
            error_types.append("Tight Fulfilment Window")

    # Quantity
    try:
        qty=int(row.get("Total Quantity",0))
        if qty<=0:   errors.append(f"Total Quantity must be > 0"); error_types.append("Invalid Quantity")
        elif qty<15: warnings.append(f"Quantity <b>{qty}</b> below MOQ threshold of 15"); error_types.append("Low Quantity")
    except (TypeError, ValueError): errors.append("Total Quantity non-numeric"); error_types.append("Data Error")

    # Case-pack
    try:
        cp=int(row.get("Case-pack",0))
        if cp<=0:   errors.append("Case-pack must be > 0"); error_types.append("Invalid Case-pack")
        elif cp==1: warnings.append("Case-pack of <b>1</b> — verify with vendor"); error_types.append("Case-pack = 1")
    except (TypeError, ValueError): errors.append("Case-pack non-numeric"); error_types.append("Data Error")

    # Location
    loc=str(row.get("Location","")).strip()
    if loc and loc not in VALID_LOCATIONS:
        warnings.append(f"Unrecognised DC location: <b>{loc}</b>")
        error_types.append("Unknown Location")

    status=("FAIL" if errors else ("WARN" if warnings else "PASS"))
    return {
        "label":label,"status":status,"risk":get_risk(errors,warnings),
        "readiness":readiness(errors,warnings),
        "errors":errors,"warnings":warnings,"error_types":list(set(error_types)),
        "vendor_name":str(row.get("Vendor Name","Unknown")).strip(),
        "po_id":str(row.get("PO_ID","")).strip(),
        "division":str(row.get("Division","")).strip(),
        "revenue":revenue,"cost_val":cost_val,
        "gross_margin":revenue-cost_val,
        "margin_gap":margin_gap,"margin_pct":margin_pct,
        "ship_month":ship_month,"window_days":window_days,
        "is_flagged":status in ("FAIL","WARN"),
    }

# ── AI ────────────────────────────────────────────────────────────────────────
def get_ai_explanation(label,errors,warnings,model="llama3.2:1b"):
    issues=errors+warnings
    if not issues: return None
    clean=[i.replace("<b>","").replace("</b>","") for i in issues]
    prompt=f"""You are a terse retail buyer at a luxury department store reviewing a flagged PO.
Row: {label}
Issues: {'; '.join(clean)}
2 sentences only. Sentence 1: Business impact with exact numbers. Sentence 2: Concrete fix before resubmission. No preamble."""
    response = ask_llm(prompt, model=model)
    if response and not response.startswith("AI Error:"):
        return response.strip()
    return f"Flagged issue: {clean[0]}. Correct all flagged fields before resubmitting this PO."

# ── Aggregations ──────────────────────────────────────────────────────────────
def build_financial(results):
    total_rev     = sum(r["revenue"]      for r in results)
    total_cost    = sum(r["cost_val"]     for r in results)
    total_gm      = sum(r["gross_margin"] for r in results)
    avg_margin    = total_gm/total_rev*100 if total_rev>0 else 0
    flagged_rows  = [r for r in results if r["is_flagged"]]
    at_risk_cost  = sum(r["cost_val"]     for r in flagged_rows)
    at_risk_rev   = sum(r["revenue"]      for r in flagged_rows)
    margin_gap    = sum(r["margin_gap"]   for r in results)

    # PO-level pass rate
    po_statuses={}
    for r in results:
        pid=r["po_id"]
        if pid not in po_statuses: po_statuses[pid]=True
        if r["is_flagged"]: po_statuses[pid]=False
    po_pass_rate  = sum(1 for v in po_statuses.values() if v)/len(po_statuses)*100 if po_statuses else 0
    unique_pos_at_risk = sum(1 for v in po_statuses.values() if not v)

    # True ROI
    flagged_count     = len(flagged_rows)
    batch_hrs_saved   = flagged_count * BATCH_RUN_HRS
    rework_hrs_saved  = flagged_count * REWORK_MINS / 60
    validation_hrs    = len(results) * (20/60)
    total_hrs_saved   = batch_hrs_saved + rework_hrs_saved + validation_hrs
    cost_saved_run    = total_hrs_saved * ANALYST_RATE
    annual_saving     = cost_saved_run * RUNS_PER_MONTH * 12

    return {
        "total_rev":total_rev,"total_cost":total_cost,"total_gm":total_gm,
        "avg_margin":avg_margin,"at_risk_cost":at_risk_cost,"at_risk_rev":at_risk_rev,
        "margin_gap":margin_gap,"po_pass_rate":po_pass_rate,
        "unique_pos_at_risk":unique_pos_at_risk,"total_pos":len(po_statuses),
        "flagged_count":flagged_count,"total_hrs_saved":total_hrs_saved,
        "cost_saved_run":cost_saved_run,"annual_saving":annual_saving,
        "batch_hrs_saved":batch_hrs_saved,
    }

def build_error_analysis(results):
    error_costs = {
        "Low Margin":             {"count":0,"cost_per":2100,"severity":"HIGH"},
        "Tight Fulfilment Window":{"count":0,"cost_per":890, "severity":"HIGH"},
        "Missing Fields":         {"count":0,"cost_per":340, "severity":"MEDIUM"},
        "Sub-Class Mismatch":     {"count":0,"cost_per":220, "severity":"LOW"},
        "Case-pack = 1":          {"count":0,"cost_per":180, "severity":"LOW"},
        "Low Quantity":           {"count":0,"cost_per":180, "severity":"LOW"},
        "Cancel Before Ship":     {"count":0,"cost_per":3200,"severity":"CRITICAL"},
        "Retail Discrepancy":     {"count":0,"cost_per":260, "severity":"MEDIUM"},
        "Invalid Division":       {"count":0,"cost_per":150, "severity":"LOW"},
        "Unknown Location":       {"count":0,"cost_per":150, "severity":"LOW"},
        "Data Error":             {"count":0,"cost_per":120, "severity":"LOW"},
    }
    for r in results:
        for et in r["error_types"]:
            if et in error_costs:
                error_costs[et]["count"]+=1
    total = sum(v["count"] for v in error_costs.values()) or 1
    out = []
    for name,d in error_costs.items():
        if d["count"]>0:
            out.append({
                "name":name,"count":d["count"],
                "pct":d["count"]/total*100,
                "est_cost":d["count"]*d["cost_per"],
                "severity":d["severity"],
            })
    return sorted(out,key=lambda x:x["count"],reverse=True)

def build_sla(results):
    windows = [r["window_days"] for r in results if r["window_days"] is not None]
    meets_sla = sum(1 for w in windows if w>=14)
    tight     = sum(1 for w in windows if 0<=w<14)
    critical  = sum(1 for w in windows if w<7 and w>=0)
    breached  = sum(1 for w in windows if w<0)
    avg_win   = sum(windows)/len(windows) if windows else 0
    sla_rate  = meets_sla/len(windows)*100 if windows else 0

    # Vendor SLA
    vnd_sla={}
    for r in results:
        v=r["vendor_name"]
        if v not in vnd_sla: vnd_sla[v]={"windows":[],"flagged":0,"total":0}
        if r["window_days"] is not None: vnd_sla[v]["windows"].append(r["window_days"])
        vnd_sla[v]["total"]+=1
        if r["is_flagged"]: vnd_sla[v]["flagged"]+=1
    vnd_sla_list=[]
    for v,d in vnd_sla.items():
        avg=sum(d["windows"])/len(d["windows"]) if d["windows"] else 0
        meets=sum(1 for w in d["windows"] if w>=14)
        compliance=meets/len(d["windows"])*100 if d["windows"] else 0
        vnd_sla_list.append({"vendor":v,"avg_window":avg,"compliance":compliance,
                             "total":d["total"],"flagged":d["flagged"]})
    return {
        "sla_rate":sla_rate,"avg_window":avg_win,"meets_14":meets_sla,
        "tight":tight,"critical":critical,"breached":breached,
        "total_rows":len(windows),
        "vendors":sorted(vnd_sla_list,key=lambda x:x["compliance"])
    }

def build_vendor_scorecard(results):
    vendors={}
    for r in results:
        v=r["vendor_name"]
        if v not in vendors:
            vendors[v]={"total":0,"flagged":0,"errors":0,"warnings":0,
                       "revenue":0.0,"cost_val":0.0,"margin_gap":0.0,
                       "gross_margin":0.0,"margins":[]}
        vendors[v]["total"]+=1
        vendors[v]["revenue"]+=r["revenue"]
        vendors[v]["cost_val"]+=r["cost_val"]
        vendors[v]["gross_margin"]+=r["gross_margin"]
        vendors[v]["margin_gap"]+=r["margin_gap"]
        if r["margin_pct"]: vendors[v]["margins"].append(r["margin_pct"])
        if r["is_flagged"]:
            vendors[v]["flagged"]+=1
            vendors[v]["errors"]+=len(r["errors"])
            vendors[v]["warnings"]+=len(r["warnings"])
    out=[]
    for v,d in vendors.items():
        er=(d["flagged"]/d["total"]*100) if d["total"]>0 else 0
        avg_margin=sum(d["margins"])/len(d["margins"]) if d["margins"] else 0
        # Weighted risk score: error_rate(30%) + exposure(40%) + margin_health(30%)
        exposure_score = min(d["revenue"]/100000*10,40)
        margin_score   = max(0,30-(avg_margin-45)) if avg_margin<50 else 0
        risk_score     = (er*0.30) + exposure_score + margin_score
        grade,gcls     = vendor_grade(er)

        # Action recommendation
        if er>=80:    action="Immediate vendor review — suspend new POs pending audit"
        elif er>=60:  action="Place on probation — mandatory training before next submission"
        elif er>=40:  action="Issue formal warning — require pre-submission check"
        elif er>=20:  action="Monitor closely — schedule vendor performance review"
        else:         action="Maintain — continue standard monitoring"

        out.append({**d,"vendor":v,"error_rate":er,"avg_margin":avg_margin,
                   "risk_score":min(risk_score,100),"grade":grade,"grade_cls":gcls,
                   "action":action,"resubmissions":d["errors"]+d["warnings"]})
    return sorted(out,key=lambda x:x["risk_score"],reverse=True)

def build_division(results):
    divs={}
    for r in results:
        d=r["division"] or "Unknown"
        if d not in divs:
            divs[d]={"total":0,"flagged":0,"revenue":0.0,"cost_val":0.0,
                    "gross_margin":0.0,"margins":[],"margin_gaps":0.0}
        divs[d]["total"]+=1
        divs[d]["revenue"]+=r["revenue"]
        divs[d]["cost_val"]+=r["cost_val"]
        divs[d]["gross_margin"]+=r["gross_margin"]
        divs[d]["margin_gaps"]+=r["margin_gap"]
        if r["margin_pct"]: divs[d]["margins"].append(r["margin_pct"])
        if r["is_flagged"]: divs[d]["flagged"]+=1
    out=[]
    for d,v in divs.items():
        er=(v["flagged"]/v["total"]*100) if v["total"]>0 else 0
        avg_m=sum(v["margins"])/len(v["margins"]) if v["margins"] else 0
        gm_pct=v["gross_margin"]/v["revenue"]*100 if v["revenue"]>0 else 0
        risk="HIGH" if er>=50 or avg_m<45 else ("MEDIUM" if er>=25 or avg_m<47 else "LOW")
        out.append({**v,"division":d,"error_rate":er,"avg_margin":avg_m,
                   "gm_pct":gm_pct,"risk":risk})
    return sorted(out,key=lambda x:x["revenue"],reverse=True)

def build_timeline(results):
    months={}
    for r in results:
        m=r["ship_month"] or "Unknown"
        if m not in months:
            months[m]={"total":0,"flagged":0,"revenue":0.0,"cost_val":0.0,"margins":[]}
        months[m]["total"]+=1
        months[m]["revenue"]+=r["revenue"]
        months[m]["cost_val"]+=r["cost_val"]
        if r["margin_pct"]: months[m]["margins"].append(r["margin_pct"])
        if r["is_flagged"]: months[m]["flagged"]+=1
    out=[]
    for m,d in sorted(months.items()):
        avg_m=sum(d["margins"])/len(d["margins"]) if d["margins"] else 0
        flag_rate=d["flagged"]/d["total"]*100 if d["total"]>0 else 0
        out.append({**d,"month":m,"avg_margin":avg_m,"flag_rate":flag_rate,
                   "gross_margin":d["revenue"]-d["cost_val"]})
    return out


def build_prioritized_actions(results, fin, vendor_sc, div_sc, sla, err_trend):
    """Prioritized actions with trade-offs — what to do, in what order, and why."""
    actions = []

    # P1 — Cancel before ship (most critical — scheduling error)
    cancel_breach = [r for r in results if r["window_days"] is not None and r["window_days"] < 0]
    if cancel_breach:
        pos = list(set(r["po_id"] for r in cancel_breach))
        actions.append({
            "priority": 1, "urgency": "CRITICAL",
            "title": f"Fix {len(cancel_breach)} cancel-before-ship scheduling errors immediately",
            "what": f"POs {', '.join(pos[:3])} have cancel dates before ship dates — these will fail at batch run",
            "do_this": "Contact vendor to renegotiate dates before submitting. Do not process as-is.",
            "tradeoff": "Submitting risks a full batch run failure + 2.5hr delay. Holding costs 1 day.",
            "impact": f"INR {sum(r['cost_val'] for r in cancel_breach):,.0f} committed spend at risk",
            "recommendation": "HOLD"
        })

    # P2 — Grade D vendors with >INR 500K exposure
    critical_vendors = [v for v in vendor_sc if v["grade"] == "D" and v["revenue"] > 500000]
    if critical_vendors:
        names = ", ".join(v["vendor"] for v in critical_vendors[:2])
        actions.append({
            "priority": 2, "urgency": "CRITICAL",
            "title": f"Escalate {len(critical_vendors)} Grade D vendor(s) to buying director",
            "what": f"{names} have >60% error rates on high-value POs — systemic quality failure",
            "do_this": "Schedule formal vendor review within 48hrs. Require pre-submission sign-off for all future POs.",
            "tradeoff": "Accepting these POs risks INR " + f"{sum(v['revenue'] for v in critical_vendors):,.0f} in margin-eroding orders. Escalating delays 1–2 days but protects margin.",
            "impact": f"INR {sum(v['margin_gap'] for v in critical_vendors):,.0f} margin gap across these vendors",
            "recommendation": "ESCALATE"
        })

    # P3 — Margin gap > INR 50K in a division
    high_gap_divs = [d for d in div_sc if d["margin_gaps"] > 50000]
    if high_gap_divs:
        names = ", ".join(d["division"] for d in high_gap_divs[:2])
        actions.append({
            "priority": 3, "urgency": "WARNING",
            "title": f"Renegotiate {names} vendor costs before next buy cycle",
            "what": f"Margin gap exceeds INR 50K in these divisions — structural pricing problem, not one-off",
            "do_this": "Pull top 5 vendors by margin gap in each division. Present cost renegotiation targets to merchant team within 2 weeks.",
            "tradeoff": "Processing now locks in below-floor margins. Renegotiating may delay floor dates by 1–2 weeks but recovers long-term profitability.",
            "impact": f"INR {sum(d['margin_gaps'] for d in high_gap_divs):,.0f} total margin gap to recover",
            "recommendation": "PROCESS WITH FLAG"
        })

    # P4 — SLA compliance below 80%
    if sla["sla_rate"] < 80:
        bottom_vendors = [v for v in sla["vendors"] if v["compliance"] < 50][:3]
        actions.append({
            "priority": 4, "urgency": "WARNING",
            "title": f"Address SLA compliance — {sla['sla_rate']:.0f}% vs 80% target",
            "what": f"{len(bottom_vendors)} vendors consistently submitting tight windows — operational risk at scale",
            "do_this": "Issue revised vendor compliance guidelines. Add minimum 35-day window requirement to vendor contracts at next renewal.",
            "tradeoff": "Accepting short windows risks late receipts and markdowns. Adding buffer increases lead time but protects sell-through.",
            "impact": f"{sla['tight']} lines below SLA · avg window {sla['avg_window']:.0f} days",
            "recommendation": "PROCESS WITH FLAG"
        })

    # P5 — Low margin rows that are close to 45% (salvageable)
    salvageable = [r for r in results if r["margin_pct"] and 40 <= r["margin_pct"] < 45]
    if salvageable:
        total_gap = sum(r["margin_gap"] for r in salvageable)
        actions.append({
            "priority": 5, "urgency": "OPPORTUNITY",
            "title": f"Recover {len(salvageable)} near-threshold PO lines with minor price adjustments",
            "what": f"These lines are within 5% of the 45% floor — small retail price increases close the gap",
            "do_this": "Increase retail by 3–8% on affected lines. Most vendors will accept retail adjustments without cost renegotiation.",
            "tradeoff": "Processing as-is loses INR " + f"{total_gap:,.0f} in margin. A 5% retail increase on these lines recovers most of the gap with minimal sell-through risk.",
            "impact": f"INR {total_gap:,.0f} recoverable margin gap across {len(salvageable)} lines",
            "recommendation": "HOLD"
        })

    return actions


def build_decision_support(results, vendor_sc):
    """For each at-risk PO — hold vs submit decision with cost of each option."""
    po_groups = {}
    for r in results:
        pid = r["po_id"] or "Unknown"
        if pid not in po_groups: po_groups[pid] = []
        po_groups[pid].append(r)

    decisions = []
    for po_id, rows in po_groups.items():
        flagged = [r for r in rows if r["is_flagged"]]
        if not flagged: continue

        total_cost    = sum(r["cost_val"] for r in rows)
        total_rev     = sum(r["revenue"] for r in rows)
        margin_gap    = sum(r["margin_gap"] for r in rows)
        avg_readiness = sum(r["readiness"] for r in rows) / len(rows)
        error_count   = sum(len(r["errors"]) for r in rows)
        warn_count    = sum(len(r["warnings"]) for r in rows)
        has_critical  = any(r["window_days"] is not None and r["window_days"] < 0 for r in rows)
        has_missing   = any("missing" in " ".join(r["errors"]).lower() for r in rows)

        # Cost of submitting as-is
        cost_of_submit = margin_gap + (2.5 * 15 if error_count > 0 else 0)  # margin loss + rework
        # Cost of holding
        cost_of_hold   = total_cost * 0.002  # 0.2% delay cost per day

        if has_critical or has_missing or error_count >= 2:
            recommendation = "HOLD"
            reason = "Critical errors present — batch run will fail. Fix before submitting."
        elif margin_gap > 5000:
            recommendation = "REVIEW"
            reason = f"INR {margin_gap:,.0f} margin gap — escalate to merchant before processing."
        elif warn_count > 0 and error_count == 0:
            recommendation = "PROCESS WITH FLAG"
            reason = "Warnings only — acceptable to process. Flag for next buy review."
        else:
            recommendation = "PROCESS"
            reason = "All checks passed. Clear to submit."

        decisions.append({
            "po_id": po_id, "lines": len(rows), "flagged": len(flagged),
            "total_cost": total_cost, "total_rev": total_rev,
            "margin_gap": margin_gap, "readiness": avg_readiness,
            "cost_of_submit": cost_of_submit, "cost_of_hold": cost_of_hold,
            "recommendation": recommendation, "reason": reason,
            "error_count": error_count, "warn_count": warn_count,
        })

    return sorted(decisions, key=lambda x: x["readiness"])


def build_pattern_intelligence(results, vendor_sc, err_trend):
    """Learning layer — what patterns exist, what they predict, what to do."""
    patterns = []

    # Pattern 1 — Systemic margin compression
    low_margin_count = sum(1 for r in results if r["margin_pct"] and r["margin_pct"] < 45)
    low_margin_pct   = low_margin_count / len(results) * 100 if results else 0
    if low_margin_pct > 30:
        patterns.append({
            "icon": "📉", "type": "SYSTEMIC",
            "title": f"{low_margin_pct:.0f}% of lines below margin floor — structural issue, not random",
            "detail": "When >30% of lines fail margin, the problem is buying strategy or vendor mix — not individual errors. Single-line fixes won't solve this.",
            "signal": "Recommendation: Review cost negotiation strategy with merchant director. Consider vendor consolidation.",
        })

    # Pattern 2 — Repeat offender vendors
    repeat_d = [v for v in vendor_sc if v["grade"] == "D" and v["total"]>=3]
    if len(repeat_d) >= 2:
        patterns.append({
            "icon": "🔁", "type": "REPEAT OFFENDER",
            "title": f"{len(repeat_d)} vendors consistently Grade D — not a training problem, a selection problem",
            "detail": "Vendors with persistent high error rates rarely improve without structural intervention. Training alone has <20% success rate at this error level.",
            "signal": "Recommendation: Vendor performance clause in next contract renewal. Consider replacement sourcing for bottom 2 vendors.",
        })

    # Pattern 3 — Division concentration
    div_errors = {}
    for r in results:
        d = r["division"] or "Unknown"
        if d not in div_errors: div_errors[d] = 0
        if r["is_flagged"]: div_errors[d] += 1
    worst_div = max(div_errors, key=div_errors.get) if div_errors else None
    if worst_div and div_errors[worst_div] > len(results) * 0.2:
        patterns.append({
            "icon": "🎯", "type": "CONCENTRATION RISK",
            "title": f"{worst_div} driving disproportionate error volume — {div_errors[worst_div]} flagged lines",
            "detail": "When one division drives >20% of all errors, the issue is usually a specific buyer, vendor relationship, or seasonal buying pattern.",
            "signal": f"Recommendation: Audit {worst_div} buying process specifically. Identify top 3 error vendors in this division.",
        })

    # Pattern 4 — SLA window trending short
    windows = [r["window_days"] for r in results if r["window_days"] is not None and r["window_days"] >= 0]
    if windows:
        avg_w = sum(windows) / len(windows)
        tight_pct = sum(1 for w in windows if w < 14) / len(windows) * 100
        if tight_pct > 25:
            patterns.append({
                "icon": "⏰", "type": "LEAD TIME COMPRESSION",
                "title": f"Avg fulfilment window {avg_w:.0f} days — {tight_pct:.0f}% below 14-day minimum",
                "detail": "Short fulfilment windows indicate vendor capacity pressure or late order placement. This predicts higher cancel rates and markdown risk next season.",
                "signal": "Recommendation: Move order placement 3 weeks earlier next buy cycle. Add window minimums to vendor SLA agreements.",
            })

    # Pattern 5 — Positive pattern (what's working)
    grade_a = [v for v in vendor_sc if v["grade"] == "A"]
    if grade_a:
        total_rev_a = sum(v["revenue"] for v in grade_a)
        patterns.append({
            "icon": "✅", "type": "BEST PRACTICE",
            "title": f"{len(grade_a)} Grade A vendors delivering clean submissions — replicate this model",
            "detail": f"These vendors represent INR {total_rev_a:,.0f} in error-free PO value. Understanding what they do differently is as important as fixing what's broken.",
            "signal": "Recommendation: Document Grade A vendor onboarding process. Use as template for new vendor setup.",
        })

    return patterns


def build_recommendations(results, fin, vendor_sc, div_sc, sla):
    recs=[]
    # High risk vendors
    high_risk=[v for v in vendor_sc if v["error_rate"]>=60 and v["total"]>=3]
    if high_risk:
        names=", ".join(v["vendor"] for v in high_risk[:3])
        total_exp=sum(v["revenue"] for v in high_risk)
        recs.append({
            "priority":1,"type":"CRITICAL",
            "title":f"Place {len(high_risk)} Grade D vendor(s) on probation — action required",
            "detail":f"{names} have error rates above 60% — immediate vendor review required",
            "impact":f"INR {total_exp:,.0f} revenue at risk · {sum(v['resubmissions'] for v in high_risk)} resubmissions pending"
        })
    # Margin below 45% avg in a division
    low_margin_div=[d for d in div_sc if d["avg_margin"]<45]
    if low_margin_div:
        names=", ".join(d["division"] for d in low_margin_div)
        recs.append({
            "priority":2,"type":"WARNING",
            "title":f"Renegotiate pricing in {names}",
            "detail":f"Average margin below 45% floor — review cost structures with key vendors",
            "impact":f"INR {sum(d['margin_gaps'] for d in low_margin_div):,.0f} total margin gap to close"
        })
    # SLA compliance
    if sla["sla_rate"]<80:
        recs.append({
            "priority":3,"type":"WARNING",
            "title":f"Address fulfilment window compliance — currently {sla['sla_rate']:.0f}% (target 80%)",
            "detail":f"{sla['tight']} PO lines have windows below 14 days — renegotiate lead times",
            "impact":f"Avg window {sla['avg_window']:.0f} days · {sla['critical']} critically tight (<7 days)"
        })
    # Pass rate
    if fin["po_pass_rate"]<70:
        recs.append({
            "priority":4,"type":"WARNING",
            "title":f"PO submission quality below target — {fin['po_pass_rate']:.0f}% PO pass rate",
            "detail":"Consider mandatory pre-submission validation training for buying team",
            "impact":f"{fin['unique_pos_at_risk']} of {fin['total_pos']} POs require rework before processing"
        })
    # Positive
    if fin["avg_margin"]>=47:
        recs.append({
            "priority":5,"type":"POSITIVE",
            "title":f"Overall margin health strong at {fin['avg_margin']:.1f}%",
            "detail":"Portfolio-level margin above 45% floor — focus on vendor-specific outliers",
            "impact":f"INR {fin['total_gm']:,.0f} gross margin protected across {fin['total_pos']} POs"
        })
    return recs

# The UI now executes the modular domain engine. The legacy local functions
# above remain temporarily until the complete v6 regression suite is finished.
from domain import po_engine as engine_module
importlib.reload(engine_module)
from domain.po_engine import (
    build_decision_support,
    build_division,
    build_financial,
    build_sla,
    build_vendor_scorecard,
    validate_row,
)

# ── MAIN UI ───────────────────────────────────────────────────────────────────
st.markdown("""<style>
:root {--bg:#0b1020;--surface:#151d31;--surface2:#11182a;--border:#2b3855;--ink:#eef2ff;--ink2:#c4cde0;--ink3:#93a1bd;}
.stApp,.main,[data-testid="stAppViewContainer"],[data-testid="stHeader"]{background:#0b1020;color:#eef2ff;}
.block-container{max-width:1600px;padding-top:1.4rem;}
[data-testid="stSidebar"]{background:#11182a;border-right:1px solid #28334d;}
h1,h2,h3{letter-spacing:-.025em;font-family:inherit;}
.po-eyebrow{color:#9fb0ff;font-size:.76rem;font-weight:800;letter-spacing:.15em;text-transform:uppercase;}
.po-hero{border:1px solid #293653;background:linear-gradient(135deg,#17213a,#10182a);border-radius:16px;padding:22px 24px;margin:.75rem 0 1.2rem;}
.po-hero-title{font-size:1.2rem;font-weight:750;margin-bottom:.35rem;}
.po-hero-copy{color:#a8b4c8;max-width:850px;line-height:1.55;}
.workflow-strip{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;background:transparent;border:0;overflow:visible;margin:.4rem 0 1.4rem;}
.workflow-step{background:#151d31;border:1px solid #2b3855!important;border-radius:12px;padding:16px;}
.workflow-step .step{color:#93a1bd;font-family:inherit;}
.workflow-step .name{font-size:.9rem;margin-top:7px;font-family:inherit;color:#eef2ff;}
[data-testid="stMetric"]{background:#151d31;border:1px solid #2b3855;border-top:3px solid #7f91ef;padding:15px;border-radius:14px;}
.stTabs [data-baseweb="tab-list"]{gap:7px;border-bottom:1px solid #303b55;}
.stTabs [data-baseweb="tab"]{padding:9px 15px;}
div[data-testid="stDataFrame"]{border:1px solid #2b3855;border-radius:10px;}
@media(max-width:900px){.workflow-strip{grid-template-columns:1fr 1fr;}}
@media(max-width:540px){.workflow-strip{grid-template-columns:1fr;}}
</style>""", unsafe_allow_html=True)
apply_theme()
st.markdown('<div class="po-eyebrow">Retail Intelligence Platform · Specialist workbench</div>', unsafe_allow_html=True)
st.title("PO / Buying Intelligence")
st.link_button("Open retail decision workspace", __import__("os").environ.get("RETAIL_APP_URL", "http://localhost:8508"))
st.caption("Purchase-order readiness, commercial risk and accountable buying decisions")
st.markdown('<div class="po-hero"><div class="po-hero-title">From buysheet to release readiness</div>'
            '<div class="po-hero-copy">Validate purchase orders, review vendor and delivery risks, and prioritize corrections. '
            'Connected requests share current vendor and Catalog prerequisites with Retail Intelligence.</div></div>', unsafe_allow_html=True)
render_workflow()

with st.sidebar:
    st.markdown('<div class="po-eyebrow">Retail intelligence ecosystem</div>', unsafe_allow_html=True)
    st.header("PO / Buying Intelligence")
    st.caption("Buying operations workspace")
    st.info("Rule-based analysis is available. Ollama adds optional explanations.")
    st.divider()
    st.subheader("Platform Workflow")
    st.markdown(
        """
        1. **Upload** purchase-order buysheet
        2. **Validate** commercial and operational rules
        3. **Assess** financial, vendor and SLA exposure
        4. **Prioritize** leadership actions
        5. **Export** the executive decision report
        """
    )
    st.divider()
    with st.expander("Optional explanations", expanded=False):
        st.caption("Narrative assistance is separate from deterministic validation and release decisions.")
        ai_enabled = st.toggle("Enable AI explanations", value=False)
        model_choice = st.selectbox("Explanation model", ["llama3.2:1b", "llama3.2"], index=0)
        ai_row_cap = st.slider("Maximum explained rows", 1, 10, 5)
    st.markdown("---")
    st.markdown(f"""**Validation Rules**

*17 mandatory fields*

Business Logic
- Margin ≥ 45%
- Division ↔ Sub-Class
- Original Retail ≥ Reg Retail

SLA Standards
- Fulfilment window ≥ 14 days
- Cancel after Ship Date

Quantity
- MOQ threshold: 15 units
- Case-pack = 1 flagged
- Quantity must be a whole multiple of case-pack

---
Deterministic buying controls · policy 1.0
""")

from workflow_connection import workflow
testing=st.toggle('Standalone testing mode',value=False,help='Assess buying rules in isolation; connected mode also checks current vendor and Catalog prerequisites.')
shared_store,shared_batch=(None,None) if testing else workflow.batch_selector('po')
if testing:st.warning('Standalone test results do not authorize shared PO execution.')
else:st.caption('PO requests must identify Vendor ID + SKU + category (or Class) + gender (or Gender). Select the batch used in Onboarding and Catalog.')
intake_actor=st.text_input('PO request recorded by',help='Your name, retained with the versioned buying request.') if not testing else 'Standalone test'

with st.expander("Upload or replace data",expanded=True):
    st.caption("INR-only prototype: all cost and retail amounts must be INR. Files without a currency column use this declared INR template; explicit blank or other currencies are blocked and excluded from INR totals. No currency conversion.")
    uploaded=st.file_uploader("PO dataset",type=["csv","xlsx","xls"],help="CSV and Excel buysheets; required fields are checked before assessment.")
    validate_clicked=st.button("Validate PO data",type="primary",use_container_width=True)
source_digest=hashlib.sha256(("connected-casepack-v2:"+str(shared_batch)+str(testing)).encode()+uploaded.getvalue()).hexdigest() if uploaded else None
if st.session_state.get("po_source_digest") != source_digest:
    st.session_state.pop("po_analysis",None)

if uploaded is None:
    st.info("Awaiting buysheet · Upload a file to begin. No purchase orders have been assessed in this session.")

if uploaded:
    try:
        file_name = uploaded.name.lower()
        df=pd.read_csv(uploaded) if file_name.endswith(".csv") else pd.read_excel(uploaded)
    except Exception as e:
        st.error(f"Could not read file: {e}"); st.stop()

    input_validation = validate_upload(df)
    df = input_validation.dataframe
    if input_validation.errors:
        for message in input_validation.errors:
            st.error(message)
        st.stop()
    for message in input_validation.warnings:
        st.warning(message)

    st.markdown(f"<p style='font-family:Arial,sans-serif;font-size:0.75rem;color:var(--ink3);margin-bottom:12px'>{uploaded.name} &nbsp;·&nbsp; {len(df):,} rows &nbsp;·&nbsp; {df['PO_ID'].nunique() if 'PO_ID' in df.columns else '?'} POs &nbsp;·&nbsp; {len(df.columns)} columns</p>",unsafe_allow_html=True)

if validate_clicked:

    if not uploaded:
        st.error("Please upload a buysheet before running validation.")
        st.stop()

    with st.spinner("Processing..."):
        results = [validate_row(row, i) for i, row in df.iterrows()]

    if not testing:
        try:
            if not shared_batch:raise ValueError('Select a shared workflow batch before validating.')
            identifiers=shared_store.ingest_pos(shared_batch,workflow.records(df),results,intake_actor)
            gates=shared_store.gates(identifiers)
            for result,identifier in zip(results,identifiers):
                blockers=gates[identifier]
                if blockers:
                    result['errors'] += [team+': '+message for team,message in blockers]
                    result['error_types']=sorted(set(result['error_types']+['Upstream dependency']))
                    result.update(status='FAIL',risk='HIGH',readiness=0,is_flagged=True)
            st.session_state.po_workflow_token=shared_store.token(shared_batch)
        except ValueError as exc:
            st.error(str(exc));st.stop()

    run_metadata = RunMetadata.create(uploaded.name, len(df))

    passed  = [r for r in results if r["status"] == "PASS"]
    warned  = [r for r in results if r["status"] == "WARN"]
    failed  = [r for r in results if r["status"] == "FAIL"]

    flagged = failed + warned

    ai_explanations = {}

    # ==============================
    # AI ANALYSIS
    # ==============================

    if ai_enabled and flagged:

        threshold_rows = [
            r for r in flagged
            if (
                r["risk"] == "HIGH"
                or r["readiness"] < 80
                or (r["margin_pct"] is not None and r["margin_pct"] < 45)
                or (r["window_days"] is not None and r["window_days"] < 14)
                or len(r["errors"]) > 0
            )
        ]

        top = sorted(
            threshold_rows,
            key=lambda x: (
                1 if x["risk"] == "HIGH" else 0,
                len(x["errors"]),
                x["margin_gap"],
                x["cost_val"]
            ),
            reverse=True
        )[:ai_row_cap]

        for r in top:

            exp = get_ai_explanation(
                r["label"],
                r["errors"],
                r["warnings"],
                model=model_choice
            )

            if r["risk"] == "HIGH" or len(r["errors"]) > 0:
                risk_analysis = {
                    "risk_level": r["risk"],
                    "readiness": r["readiness"],
                    "recommendation": "Hold and correct critical issues before submission.",
                    "reason": "PO has errors or high-risk threshold breach."
                }
            else:
                risk_analysis = None

            ai_explanations[r["label"]] = {
                "explanation": exp,
                "risk_analysis": risk_analysis
            }

    # ==============================
    # BUILD ANALYTICS
    # ==============================

    fin = build_financial(results)
    err_trend = build_error_analysis(results)
    sla = build_sla(results)
    vendor_sc = build_vendor_scorecard(results)
    div_sc = build_division(results)
    timeline = build_timeline(results)

    recs = build_recommendations(
        results,
        fin,
        vendor_sc,
        div_sc,
        sla
    )

    actions = build_prioritized_actions(
        results,
        fin,
        vendor_sc,
        div_sc,
        sla,
        err_trend
    )

    decisions = build_decision_support(
        results,
        vendor_sc
    )

    assessments, assessment_ids = results_to_assessments(results)
    try:
        assessment_repository = AssessmentRepository()
        assessment_repository.save_run(run_metadata)
        assessment_repository.save_assessments(
            run_metadata,
            assessments,
            assessment_ids,
        )
        assessment_repository.save_decisions(run_metadata, decisions)
        persistence_counts = assessment_repository.run_counts()
        st.caption(
            f"Run {run_metadata.run_id} saved · "
            f"{len(assessments)} PO-line assessments · "
            f"{len(decisions)} PO decisions · "
            f"{persistence_counts['runs']} stored run(s)"
        )
    except (OSError, ValueError, sqlite3.Error) as persistence_error:
        st.warning(f"Analysis completed but could not be saved: {persistence_error}")

    patterns = build_pattern_intelligence(
        results,
        vendor_sc,
        err_trend
    )
    
    executive_view = analyze_executive_decision(
        fin,
        vendor_sc,
        div_sc,
        sla,
        actions,
        decisions
    )

    publication_payload = build_publication(
        run_metadata, results, fin, vendor_sc, div_sc, sla, actions, decisions
    )
    st.session_state.po_analysis={'results':results, 'run_metadata':run_metadata, 'fin':fin, 'err_trend':err_trend, 'sla':sla, 'vendor_sc':vendor_sc, 'div_sc':div_sc, 'actions':actions, 'decisions':decisions, 'patterns':patterns, 'executive_view':executive_view, 'publication_payload':publication_payload, 'ai_explanations':ai_explanations}
    st.session_state.po_source_digest=source_digest

if not testing and shared_batch:
    with st.expander('Shared requests, ownership and approvals',expanded=False):
        workflow.summary(shared_store,shared_batch,'po')
        workflow.actions(shared_store,shared_batch,'po',key='po_shared_actions')
        workflow.review(shared_store,shared_batch,'po',key='po_shared_review')
        workflow.evidence(shared_store,shared_batch,key='po_shared_evidence')
    if st.session_state.get('po_analysis') and st.session_state.get('po_workflow_token')!=shared_store.token(shared_batch):
        st.warning('The shared workflow changed. Validate PO data again to refresh dependency results. Current shared approval and execution controls already use the latest versions.')
        st.session_state.pop('po_analysis',None)

if st.session_state.get("po_analysis"):
    results=st.session_state.po_analysis['results']
    run_metadata=st.session_state.po_analysis['run_metadata']
    fin=st.session_state.po_analysis['fin']
    err_trend=st.session_state.po_analysis['err_trend']
    sla=st.session_state.po_analysis['sla']
    vendor_sc=st.session_state.po_analysis['vendor_sc']
    div_sc=st.session_state.po_analysis['div_sc']
    actions=st.session_state.po_analysis['actions']
    decisions=st.session_state.po_analysis['decisions']
    patterns=st.session_state.po_analysis['patterns']
    executive_view=st.session_state.po_analysis['executive_view']
    publication_payload=st.session_state.po_analysis['publication_payload']
    ai_explanations=st.session_state.po_analysis['ai_explanations']
    render_po_run_contract(run_metadata)
    omitted=sum(not row.get("commercial_value_included",True) for row in results)
    st.caption(f"Currency: INR · {len(results)-omitted:,}/{len(results):,} lines have INR currency. {omitted:,} missing/non-INR lines are excluded from commercial totals and remain blocked.")
    if not testing:
        st.caption('These PO request versions are already visible in Retail Intelligence under the selected batch. Human approval and simulated execution remain separate controls.')
    else:
        st.subheader("Publish to Retail Intelligence",help="Send the validated PO evidence for the shared launch decision.")
        configured=bool(os.getenv("RETAIL_INTELLIGENCE_API_URL") and os.getenv("RETAIL_INTELLIGENCE_API_TOKEN") and publication_payload.get("business_cycle_id"))
        publication=publication_state(publication_payload)
        if st.button("Publish to Retail Intelligence",type="primary",disabled=not configured):
            with st.spinner("Sending assessed PO results…"):
                publication=publish(publication_payload)
            if publication.get("status")=="FAILED":
                st.error("Publication failed. Your assessment is retained; retry publishing.")
        if publication.get("status")=="PUBLISHED":
            st.success("Retail Intelligence acknowledged this PO assessment.")
        elif not configured:
            st.info("Publishing is not configured. Start the apps with the connected launcher.")
        else:
            st.caption("Validated evidence is ready to publish. Human approval remains a separate decision.")
    
    # ==============================
    # CLEANED EXECUTIVE TABS
    # ==============================

    def fmt_money(x):
        try:
            return f"INR {float(x):,.0f}"
        except Exception:
            return "INR 0"

    def fmt_pct(x):
        try:
            return f"{float(x):.1f}%"
        except Exception:
            return "0.0%"

    def fmt_num(x):
        try:
            return f"{float(x):,.0f}"
        except Exception:
            return "0"

    tab1, tab2, tab3, tab4 = st.tabs([
        "Executive Summary",
        "Submission & SLA",
        "Vendor Intelligence",
        "Decision & Export"
    ])

    # ==================================================
    # TAB 1: EXECUTIVE VIEW
    # ==================================================
    with tab1:
        st.subheader("PO line readiness",help="Each assessed line appears once as checks clear, review or blocked; this is not release approval.")
        st.altair_chart(bar_chart(outcome_rows(results),"Outcome","Lines","% of lines"),width="stretch")
        st.caption("Labels show line count and percentage of all assessed lines. Checks clear still requires linked vendor/catalog evidence and human review.")
        level_class = (
            "critical"
            if executive_view["decision_level"] == "CRITICAL"
            else "warning"
            if executive_view["decision_level"] == "WARNING"
            else "positive"
        )

        st.markdown(f"""<div class="exec-banner {level_class}">
<div class="icon">🧠</div>
<div class="content">
<div class="title">Executive Recommendation</div>
<div class="detail">
Revenue Reviewed: <b>INR {fin['total_rev']:,.0f}</b><br>
Financial Exposure: <b>INR {fin['at_risk_rev']:,.0f}</b><br>
Highest Risk Vendor: <b>{executive_view['top_vendor']}</b><br>
Primary Issue: <b>Margin Leakage</b><br><br>
<b>Recommended Action: {executive_view['decision']}</b>
</div>
</div>
</div>""", unsafe_allow_html=True)

        st.markdown('<div class="sec-hdr">Executive Command Center</div>', unsafe_allow_html=True)

        executive_confidence = (
            (fin["po_pass_rate"] * 0.4)
            + (sla["sla_rate"] * 0.3)
            + (fin["avg_margin"] * 0.3)
        )

        st.markdown(f"""<div class="kpi-grid" style="grid-template-columns:repeat(5,1fr);">
<div class="kpi-cell c-red">
<div class="lbl" tabindex="0" title="Severity of the overall buying recommendation based on PO, SLA and margin checks." aria-label="Decision Level: Severity of the overall buying recommendation based on PO, SLA and margin checks.">Decision Level ⓘ</div>
<div class="val" style="font-size:1.1rem;">{executive_view['decision_level']}</div>
<div class="sub">{executive_view['decision_reason']}</div>
</div>
<div class="kpi-cell c-purple">
<div class="lbl" tabindex="0" title="INR retail value on flagged PO lines; potential exposure, not booked revenue or confirmed loss." aria-label="At-Risk Revenue: INR retail value on flagged PO lines; potential exposure, not booked revenue or confirmed loss.">At-Risk Revenue ⓘ</div>
<div class="val">INR {executive_view['at_risk_revenue']:,.0f}</div>
<div class="sub">Financial exposure</div>
</div>
<div class="kpi-cell c-amber">
<div class="lbl" tabindex="0" title="Vendor with the highest computed risk score in the current assessment." aria-label="Top Vendor Risk: Vendor with the highest computed risk score in the current assessment.">Top Vendor Risk ⓘ</div>
<div class="val" style="font-size:1.1rem;">{executive_view['top_vendor']}</div>
<div class="sub">Risk score {executive_view['top_vendor_risk']:.0f}</div>
</div>
<div class="kpi-cell c-blue">
<div class="lbl" tabindex="0" title="Highest relative division priority by risk tier, error rate and margin gap; all divisions may still be low risk." aria-label="Division to Monitor: Highest relative division priority by risk tier, error rate and margin gap; all divisions may still be low risk.">Division to Monitor ⓘ</div>
<div class="val" style="font-size:1.1rem;">{executive_view['top_division']}</div>
<div class="sub">{executive_view['top_division_risk']} risk · relative priority, not necessarily high risk</div>
</div>
<div class="kpi-cell c-green">
<div class="lbl" tabindex="0" title="Diagnostic blend: 40% PO pass rate, 30% SLA rate and 30% gross margin; not a probability of success." aria-label="Executive Confidence: Diagnostic blend: 40% PO pass rate, 30% SLA rate and 30% gross margin; not a probability of success.">Executive Confidence ⓘ</div>
<div class="val">{executive_confidence:.0f}%</div>
<div class="sub">Submission confidence</div>
</div>
</div>""", unsafe_allow_html=True)

        st.markdown('<div class="sec-hdr">Financial Impact Assessment</div>', unsafe_allow_html=True)

        st.markdown(f"""
        <div class="kpi-grid" style="grid-template-columns:repeat(4,1fr);">
            <div class="kpi-cell c-blue">
                <div class="lbl" tabindex="0" title="INR regular retail price times quantity across included lines; potential retail value, not actual sales." aria-label="Total Revenue: INR regular retail price times quantity across included lines; potential retail value, not actual sales.">Total Revenue ⓘ</div>
                <div class="val">INR {fin['total_rev']:,.0f}</div>
                <div class="sub">Portfolio value</div>
            </div>
            <div class="kpi-cell c-green">
                <div class="lbl" tabindex="0" title="INR retail value less purchase cost, divided by retail value; excludes tax and operating costs." aria-label="Gross Margin: INR retail value less purchase cost, divided by retail value; excludes tax and operating costs.">Gross Margin ⓘ</div>
                <div class="val">{fin['avg_margin']:.1f}%</div>
                <div class="sub">INR {fin['total_gm']:,.0f} GM</div>
            </div>
            <div class="kpi-cell c-red">
                <div class="lbl" tabindex="0" title="INR retail value on flagged PO lines; potential exposure, not booked revenue or confirmed loss." aria-label="At-Risk Revenue: INR retail value on flagged PO lines; potential exposure, not booked revenue or confirmed loss.">At-Risk Revenue ⓘ</div>
                <div class="val">INR {fin['at_risk_rev']:,.0f}</div>
                <div class="sub">Flagged PO value</div>
            </div>
            <div class="kpi-cell c-purple">
                <div class="lbl" tabindex="0" title="Prototype scenario using INR 15 per analyst hour and 240 runs per year; not measured savings." aria-label="Annualized Savings: Prototype scenario using INR 15 per analyst hour and 240 runs per year; not measured savings.">Annualized Savings ⓘ</div>
                <div class="val">INR {fin['annual_saving']:,.0f}</div>
                <div class="sub">{fin['total_hrs_saved']:.1f} hrs/run saved</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="sec-hdr">Top Recommended Actions</div>', unsafe_allow_html=True)

        if actions:
            action_rows = []
            for a in actions[:5]:
                action_rows.append({
                    "Priority": a["priority"],
                    "Action": a["title"],
                    "Recommended Decision": a["recommendation"],
                    "Business Impact": a["impact"],
                })

            st.dataframe(
                pd.DataFrame(action_rows),
                use_container_width=True,
                hide_index=True
            )

            top_action = actions[0]
            st.markdown(f"""
            <div class="exec-banner warning">
                <div class="icon">✅</div>
                <div class="content">
                    <div class="title">Leadership Decision Required</div>
                    <div class="detail">
                        Prioritize: <b>{top_action['title']}</b><br>
                        Decision: <b>{top_action['recommendation']}</b><br>
                        Impact: <b>{top_action['impact']}</b>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.success("No priority leadership actions required.")

    # ==================================================
    # TAB 2: OPERATIONAL DIAGNOSTICS
    # ==================================================
    with tab2:
        st.subheader("What needs correction?",help="The six most frequent validation issues, measured by affected PO lines.")
        issues=issue_rows(results)
        if issues:
            st.altair_chart(bar_chart(issues,"Issue","Affected lines","% of lines"),width="stretch")
            st.caption("Percentage of all assessed lines; a line can have multiple issues, so these percentages are not additive.")
        else: st.success("No validation issues in the current PO assessment.")
        detail_table(pd.DataFrame(results),"All assessed PO lines / SKUs","po-lines",{"Run":run_metadata.run_id,"Source":run_metadata.source_file})
        detail_table(pd.DataFrame(sla["vendors"]),"Vendor SLA evidence","po-sla",{"Run":run_metadata.run_id})
        st.markdown('<div class="sec-hdr">Top Submission Risks</div>', unsafe_allow_html=True)

        if err_trend:
            risk_rows = []
            for e in err_trend:
                risk_rows.append({
                    "Risk Driver": e["name"],
                    "Impacted Lines": e["count"],
                    "Share": f"{e['pct']:.0f}%",
                    "Estimated Cost": fmt_money(e["est_cost"]),
                    "Severity": e["severity"],
                })

                risk_df = pd.DataFrame(risk_rows)

                risk_df["Severity"] = risk_df["Severity"].apply(
                    lambda x:
                                                  "🔴 HIGH" if x == "HIGH"
                    else "🟠 MEDIUM" if x == "MEDIUM"
                    else "🟢 LOW"
                )

            detail_table(risk_df,"Submission risks","po-submission-risks",{"Run":run_metadata.run_id,"Source":run_metadata.source_file})

            top_risk = err_trend[0]
            st.markdown(f"""
            <div class="exec-banner warning">
                <div class="icon">🚨</div>
                <div class="content">
                    <div class="title">Primary Submission Risk</div>
                    <div class="detail">
                        <b>{top_risk['name']}</b> is the leading risk driver,
                        impacting <b>{top_risk['count']}</b> line(s) with estimated cost of
                        <b>INR {top_risk['est_cost']:,.0f}</b>.
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.success("No major submission risks detected.")

        st.markdown('<div class="sec-hdr">SLA Compliance</div>', unsafe_allow_html=True)

        st.markdown(f"""
        <div class="kpi-grid" style="grid-template-columns:repeat(4,1fr);">
            <div class="kpi-cell c-blue">
                <div class="lbl" tabindex="0" title="Percentage of dated lines with at least 14 days between ship and cancellation dates." aria-label="SLA Rate: Percentage of dated lines with at least 14 days between ship and cancellation dates.">SLA Rate ⓘ</div>
                <div class="val">{sla['sla_rate']:.0f}%</div>
                <div class="sub">Target 80%</div>
            </div>
            <div class="kpi-cell c-green">
                <div class="lbl" tabindex="0" title="Average number of days between ship and cancellation dates for parseable dates." aria-label="Avg Window: Average number of days between ship and cancellation dates for parseable dates.">Avg Window ⓘ</div>
                <div class="val">{sla['avg_window']:.0f}</div>
                <div class="sub">Days</div>
            </div>
            <div class="kpi-cell c-amber">
                <div class="lbl" tabindex="0" title="Lines with a nonnegative delivery window shorter than 14 days." aria-label="Tight Windows: Lines with a nonnegative delivery window shorter than 14 days.">Tight Windows ⓘ</div>
                <div class="val">{sla['tight']}</div>
                <div class="sub">Below 14 days</div>
            </div>
            <div class="kpi-cell c-red">
                <div class="lbl" tabindex="0" title="Lines where the cancellation date is earlier than the ship date." aria-label="Breached: Lines where the cancellation date is earlier than the ship date.">Breached ⓘ</div>
                <div class="val">{sla['breached']}</div>
                <div class="sub">Cancel before ship</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown('<div class="sec-hdr">Leadership Decision Queue</div>', unsafe_allow_html=True)

        if decisions:
            decision_df = pd.DataFrame(decisions)[
                [
                    "po_id",
                    "recommendation",
                    "readiness",
                    "lines",
                    "flagged",
                    "margin_gap",
                    "cost_of_submit",
                    "cost_of_hold",
                    "reason"
                ]
            ]

            decision_df = decision_df.rename(columns={
                "po_id": "PO",
                "recommendation": "Recommendation",
                "readiness": "Readiness %",
                "lines": "Lines",
                "flagged": "Flagged Lines",
                "margin_gap": "Margin Gap",
                "cost_of_submit": "Cost of Submit",
                "cost_of_hold": "Cost of Hold",
                "reason": "Leadership Rationale"
            })

            decision_df["Readiness %"] = decision_df["Readiness %"].apply(lambda x: f"{x:.0f}%")
            decision_df["Margin Gap"] = decision_df["Margin Gap"].apply(fmt_money)
            decision_df["Cost of Submit"] = decision_df["Cost of Submit"].apply(fmt_money)
            decision_df["Cost of Hold"] = decision_df["Cost of Hold"].apply(fmt_money)

            detail_table(decision_df,"PO decision queue","po-decisions",{"Run":run_metadata.run_id,"Source":run_metadata.source_file})

            top_decision = decisions[0]
            st.markdown(f"""
            <div class="exec-banner warning">
                <div class="icon">🧭</div>
                <div class="content">
                    <div class="title">Recommended Leadership Decision</div>
                    <div class="detail">
                        Prioritize PO <b>{top_decision['po_id']}</b>.
                        Recommendation: <b>{top_decision['recommendation']}</b>.
                        Cost of submitting as-is is <b>INR {top_decision['cost_of_submit']:,.0f}</b>
                        versus hold cost of <b>INR {top_decision['cost_of_hold']:,.0f}</b>.
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        else:
            st.success("No at-risk PO decisions required.")

    # ==================================================
    # TAB 3: VENDOR & DIVISION INTELLIGENCE
    # ==================================================
    with tab3:
        st.subheader("Flagged commitment by division",help="Purchase cost times quantity on flagged INR lines, counted once per line and grouped by division.")
        exposure=exposure_rows(results)
        if exposure:
            st.altair_chart(bar_chart(exposure,"Division","Flagged commitment (INR)","% of flagged commitment"),width="stretch")
            st.caption("Percentage of measured flagged INR commitment. Missing/non-INR amounts are excluded; this is exposure, not confirmed loss.")
        else: st.info("No measurable flagged INR commitment in this assessment; inspect line findings for any unmeasured amounts.")
        st.markdown('<div class="sec-hdr">Vendor Risk Scorecard</div>', unsafe_allow_html=True)

        if vendor_sc:
            vendor_df = pd.DataFrame(vendor_sc)[
                [
                    "vendor",
                    "grade",
                    "total",
                    "flagged",
                    "error_rate",
                    "revenue",
                    "avg_margin",
                    "risk_score",
                ]
            ]

            vendor_df = vendor_df.rename(columns={
                "vendor": "Vendor",
                "grade": "Grade",
                "total": "Total Lines",
                "flagged": "Flagged Lines",
                "error_rate": "Error Rate %",
                "revenue": "Revenue Exposure",
                "avg_margin": "Avg Margin %",
                "risk_score": "Risk Score"
            })

            vendor_df["Error Rate %"] = vendor_df["Error Rate %"].apply(fmt_pct)
            vendor_df["Revenue Exposure"] = vendor_df["Revenue Exposure"].apply(fmt_money)
            vendor_df["Avg Margin %"] = vendor_df["Avg Margin %"].apply(fmt_pct)
            vendor_df["Risk Score"] = vendor_df["Risk Score"].apply(lambda x: f"{x:.0f}")

            detail_table(vendor_df,"Vendor scorecard","po-vendors",{"Run":run_metadata.run_id,"Source":run_metadata.source_file})

            top_vendor = vendor_sc[0]
            st.markdown(f"""
            <div class="exec-banner warning">
                <div class="icon">🏢</div>
                <div class="content">
                    <div class="title">Vendor Risk Insight</div>
                    <div class="detail">
                        <b>{top_vendor['vendor']}</b> is the highest-risk vendor,
                        with <b>{top_vendor['error_rate']:.1f}%</b> error rate,
                        <b>INR {top_vendor['revenue']:,.0f}</b> exposure,
                        and risk score of <b>{top_vendor['risk_score']:.0f}</b>.
                        Recommended action: <b>{top_vendor['action']}</b>.
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("No vendor scorecard data available.")

        st.markdown('<div class="sec-hdr">Division Performance Analysis</div>', unsafe_allow_html=True)

        if div_sc:
            div_df = pd.DataFrame(div_sc)[
                [
                    "division",
                    "total",
                    "flagged",
                    "error_rate",
                    "revenue",
                    "gross_margin",
                    "gm_pct",
                    "avg_margin",
                    "margin_gaps",
                    "risk"
                ]
            ]

            div_df = div_df.rename(columns={
                "division": "Division",
                "total": "Total Lines",
                "flagged": "Flagged Lines",
                "error_rate": "Error Rate %",
                "revenue": "Revenue",
                "gross_margin": "Gross Margin",
                "gm_pct": "GM %",
                "avg_margin": "Avg Margin %",
                "margin_gaps": "Margin Gap",
                "risk": "Risk"
            })

            div_df["Error Rate %"] = div_df["Error Rate %"].apply(fmt_pct)
            div_df["Revenue"] = div_df["Revenue"].apply(fmt_money)
            div_df["Gross Margin"] = div_df["Gross Margin"].apply(fmt_money)
            div_df["GM %"] = div_df["GM %"].apply(fmt_pct)
            div_df["Avg Margin %"] = div_df["Avg Margin %"].apply(fmt_pct)
            div_df["Margin Gap"] = div_df["Margin Gap"].apply(fmt_money)

            detail_table(div_df,"Division performance","po-divisions",{"Run":run_metadata.run_id,"Source":run_metadata.source_file})

            worst_div = sorted(div_sc, key=lambda x: (x["risk"] == "HIGH", x["error_rate"], x["revenue"]), reverse=True)[0]

            st.markdown(f"""
            <div class="exec-banner info">
                <div class="icon">📊</div>
                <div class="content">
                    <div class="title">Division Performance Insight</div>
                    <div class="detail">
                        <b>{worst_div['division']}</b> has <b>INR {worst_div['revenue']:,.0f}</b> revenue,
                        <b>{worst_div['error_rate']:.1f}%</b> error rate,
                        <b>{worst_div['avg_margin']:.1f}%</b> average margin,
                        and is classified as <b>{worst_div['risk']}</b> risk.
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        else:
            st.info("No division performance data available.")

        st.markdown('<div class="sec-hdr">Pattern Intelligence</div>', unsafe_allow_html=True)

        if patterns:
            pattern_rows = []
            for p in patterns:
                pattern_rows.append({
                    "Pattern": p["title"],
                    "Insight": p["detail"],
                    "Recommended Action": p["signal"].replace("Recommendation:", "").strip(),
                })

            st.dataframe(
                pd.DataFrame(pattern_rows),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("No major recurring patterns detected.")

    # ==================================================
    # TAB 4: AI & EXPORT
    # ==================================================
    with tab4:
        st.markdown('<div class="sec-hdr">Executive AI Insights</div>', unsafe_allow_html=True)

        insight_rows = []

        if ai_explanations:
            for label, insight in list(ai_explanations.items())[:5]:
                insight_rows.append({
                    "Risk Item": label,
                    "AI Insight": insight.get("explanation", "No explanation generated.")
                })

        if err_trend:
            top_error = err_trend[0]
            insight_rows.append({
                "Risk Item": "Top Operational Risk",
                "AI Insight": f"{top_error['name']} is the leading issue, impacting {top_error['count']} line(s) with estimated exposure of INR {top_error['est_cost']:,.0f}."
            })

        if vendor_sc:
            top_vendor = vendor_sc[0]
            insight_rows.append({
                "Risk Item": "Top Vendor Risk",
                "AI Insight": f"{top_vendor['vendor']} has the highest vendor risk score ({top_vendor['risk_score']:.0f}) with {top_vendor['error_rate']:.1f}% error rate and INR {top_vendor['revenue']:,.0f} exposure."
            })

        if div_sc:
            top_div = div_sc[0]
            insight_rows.append({
                "Risk Item": "Division to Monitor",
                "AI Insight": f"{top_div['division']} represents INR {top_div['revenue']:,.0f} in revenue with {top_div['error_rate']:.1f}% error rate and {top_div['risk']} risk classification."
            })

        if insight_rows:
            st.dataframe(
                pd.DataFrame(insight_rows).head(5),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No threshold-breach AI insights generated.")

        st.markdown('<div class="sec-hdr">Export Executive Report</div>', unsafe_allow_html=True)

        export_output = io.BytesIO()

        executive_summary_export = pd.DataFrame([{
            "Decision": executive_view.get("decision", ""),
            "Decision Level": executive_view.get("decision_level", ""),
            "At-Risk Revenue": fin.get("at_risk_rev", 0),
            "Total Revenue": fin.get("total_rev", 0),
            "Gross Margin %": fin.get("avg_margin", 0),
            "Annualized Savings": fin.get("annual_saving", 0),
            "Top Vendor": executive_view.get("top_vendor", ""),
            "Top Division": executive_view.get("top_division", ""),
            "Executive Summary": executive_view.get("executive_summary", "")
        }])

        export_workbook({
            "Executive Summary":executive_summary_export,
            "PO Validation":results,"Vendor Scorecard":vendor_sc,
            "Division Analytics":div_sc,"Risk Drivers":err_trend,
            "SLA Compliance":sla["vendors"],"Recommended Actions":actions,
            "Decision Support":decisions,"Pattern Intelligence":patterns,
        },"PO_Intelligence_Report",{"Run":run_metadata.run_id,"Source":run_metadata.source_file,"Validated at":run_metadata.validated_at})

