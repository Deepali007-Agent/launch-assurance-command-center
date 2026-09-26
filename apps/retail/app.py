"""Unified Multi-Agent Retail Intelligence Platform."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import io
import json

import pandas as pd
import streamlit as st
from orchestration.presentation import explained_metric, detail_table

from orchestration.contracts import AgentAssessment
from orchestration.executive import orchestrate
from orchestration.intake import (
    PublicationStore, catalog_publication_to_assessment,
    onboarding_publications_to_assessment, po_publication_to_assessment,
)
from orchestration.runtime import OrchestrationLedger


st.set_page_config(
    page_title="Retail Intelligence Platform",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    :root {
      --bg:#0e1117; --surface:#1b1f2a; --surface2:#262b37;
      --border:#394150; --ink:#f7f8fa; --muted:#a7afbd;
      --accent:#64d8c5; --green:#4cc38a; --amber:#ffb454;
    }
    .stApp { background:var(--bg); color:var(--ink); }
    [data-testid="stSidebar"] { background:var(--surface); }
    .rip-header {
      border:1px solid var(--border); border-left:3px solid var(--accent);
      border-radius:8px; padding:10px 16px; margin-bottom:10px;
      background:linear-gradient(120deg,#202632,#151922);
    }
    .rip-header .eyebrow {
      color:var(--accent); font-size:.7rem; font-weight:700;
      letter-spacing:1.4px; text-transform:uppercase;
    }
    .rip-header h1 { margin:0; padding:0; font-size:1.4rem; }
    .block-container { padding-top:2rem; }
    .rip-header p { color:var(--muted); margin:0; }
    .agent-card {
      border:1px solid var(--border); border-radius:7px; padding:15px 17px;
      background:var(--surface); min-height:150px;
    }
    .agent-card .name { font-weight:700; font-size:.95rem; }
    .agent-card .state { font-size:.7rem; margin-top:5px; color:var(--muted); }
    .agent-card .score { font-size:1.7rem; font-weight:800; margin-top:10px; }
    .agent-card .score-label {
      color:var(--muted); font-size:.65rem; letter-spacing:.6px;
      text-transform:uppercase; margin-top:2px;
    }
    .help-icon {
      color:var(--muted); cursor:help; font-size:.78rem; margin-left:5px;
    }
    .decision {
      border:1px solid var(--border); border-radius:8px; padding:20px 22px;
      background:var(--surface); margin:10px 0 18px;
    }
    .decision .label { color:var(--muted); font-size:.68rem; letter-spacing:1px; }
    .decision .value { font-size:1.45rem; font-weight:800; margin-top:3px; }
    div[data-testid="stMetric"] {
      background:var(--surface); border:1px solid var(--border);
      border-radius:7px; padding:13px 15px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)



# The named workspace is the sole decision authority in the user interface.
@st.cache_resource
def stores():
    return PublicationStore(), OrchestrationLedger()

st.markdown('<div class="rip-header"><h1>Launch Assurance Command Center</h1><p>Identify launch blockers, assign the next action and assess commercial impact.</p></div>',unsafe_allow_html=True)
store,ledger=stores()
with st.sidebar:
    st.header('Supporting tools')
    st.caption('Select the same shared batch in each workbench. Earlier saved assessments are available in History.')
    st.link_button('Vendor workbench',__import__("os").environ.get("ONBOARDING_APP_URL", 'http://localhost:8509'))
    st.link_button('Catalog workbench',__import__("os").environ.get("CATALOG_APP_URL", 'http://localhost:8507'))
    st.link_button('Buying workbench',__import__("os").environ.get("PO_APP_URL", 'http://localhost:8510'))
    with st.expander('Connection diagnostics'):
        st.json(store.health_summary())
import importlib
from retail_workflow import store as workflow_store, ui as workflow_ui
importlib.reload(workflow_store)
importlib.reload(workflow_ui)
from retail_workflow.auto_intake_ui import render as render_auto_intake
with st.sidebar:
    render_auto_intake()
batches=workflow_store.WorkflowStore().batches()
launch_names={row['id']:row['name'] for row in batches}
options=['demo']+['uploaded:'+key for key in launch_names]+['new_upload']
if st.session_state.get('launch_choice') not in options:
    st.session_state.pop('launch_choice',None)
with st.sidebar:
    chosen=st.selectbox('Choose launch',options,key='launch_choice',
        format_func=lambda key:'Demo · Festive Dress Launch' if key=='demo' else 'Uploaded data · Start a new batch' if key=='new_upload' else 'Uploaded data · '+launch_names[key.split(':',1)[1]],
        help='Demo includes synthetic shipment and stock inputs. Uploaded batches use the source files validated in your standalone workbenches.')
current,history=st.tabs(['Launch','History'])
with current:
    if chosen=='demo':
        from launch_assurance import ui as assurance_ui
        importlib.reload(assurance_ui).render(show_title=False)
    elif chosen=='new_upload':
        st.info('Start a named batch in Onboarding, upload Vendor and Item files, then select that batch here. Receive eligible items in Catalog and upload the PO file in Buying.')
        st.caption('After source validation, add shipment and inventory CSVs to the same batch to compare operational alternatives.')
    else:
        batch=chosen.split(':',1)[1]
        workflow_ui.workspace(selected_batch=batch)
with history:
    st.caption('Earlier saved launch assessments and their evidence. These are separate from the synthetic demonstration.')
    from orchestration.unified_workspace import render_workspace
    render_workspace(store,ledger)

from orchestration.header_definitions import render_header_definitions
render_header_definitions()

from launch_assurance.evaluation_ui import render as render_benchmark
render_benchmark()
