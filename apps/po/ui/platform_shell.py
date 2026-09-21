"""Reusable Retail Intelligence Platform shell."""

import html

import streamlit as st

from domain.contracts import RunMetadata


PLATFORM_CSS = """
<style>
.platform-nav {
    display:flex; gap:8px; align-items:center; flex-wrap:wrap;
    margin:-4px 0 18px 0;
}
.platform-nav .module {
    border:1px solid var(--border); background:var(--surface);
    padding:7px 11px; border-radius:4px;
    font:600 .69rem 'IBM Plex Sans',sans-serif; color:var(--ink2);
}
.platform-nav .module.active {
    color:#fff; background:#FF4B4B; border-color:#FF4B4B;
}
.platform-nav .module.pending::after {
    content:"NOT EVALUATED"; margin-left:7px; color:var(--amber);
    font:500 .56rem 'IBM Plex Mono',monospace;
}
.workflow-strip {
    display:grid; grid-template-columns:repeat(5,1fr);
    border:1px solid var(--border); background:var(--surface);
    margin:0 0 16px 0; border-radius:5px; overflow:hidden;
}
.workflow-step { padding:10px 12px; border-right:1px solid var(--border); }
.workflow-step:last-child { border-right:none; }
.workflow-step .step {
    color:var(--ink3); font:500 .58rem 'IBM Plex Mono',monospace;
    letter-spacing:.7px; text-transform:uppercase;
}
.workflow-step .name {
    color:var(--ink2); font:600 .72rem 'IBM Plex Sans',sans-serif;
    margin-top:2px;
}
.data-contract {
    display:grid; grid-template-columns:1.2fr .7fr .7fr .7fr;
    gap:0; border:1px solid var(--border); background:var(--surface);
    border-radius:5px; overflow:hidden; margin:8px 0 16px 0;
}
.contract-cell { padding:11px 14px; border-right:1px solid var(--border); }
.contract-cell:last-child { border-right:none; }
.contract-cell .label {
    color:var(--ink3); font:500 .58rem 'IBM Plex Mono',monospace;
    text-transform:uppercase; letter-spacing:.7px;
}
.contract-cell .value {
    color:var(--ink); font:600 .76rem 'IBM Plex Sans',sans-serif;
    margin-top:3px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
[data-baseweb="tab"][aria-selected="true"] {
    color:#FF4B4B!important;
    border-bottom-color:#FF4B4B!important;
}
@media (max-width:900px) {
    .workflow-strip { grid-template-columns:1fr; }
    .workflow-step { border-right:none; border-bottom:1px solid var(--border); }
    .data-contract { grid-template-columns:1fr 1fr; }
}
</style>
"""


def render_po_run_contract(metadata: RunMetadata) -> None:
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


def render_workflow() -> None:
    steps = [
        ("01", "Upload"),
        ("02", "Validate"),
        ("03", "Calculate KPIs"),
        ("04", "Control review"),
        ("05", "Decision"),
    ]
    cells = "".join(
        (
            '<div class="workflow-step">'
            f'<div class="step">Step {number}</div>'
            f'<div class="name">{name}</div>'
            "</div>"
        )
        for number, name in steps
    )
    st.markdown(
        f'<div class="workflow-strip">{cells}</div>',
        unsafe_allow_html=True,
    )

