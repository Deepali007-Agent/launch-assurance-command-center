"""Public portfolio entry: session-isolated synthetic launch demonstration."""
from pathlib import Path
import sys
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'apps' / 'retail'))
st.set_page_config(page_title='Launch Assurance Command Center', layout='wide')
st.session_state['_la_public_mode'] = True
st.title('Launch Assurance Command Center')
st.write('Decide what can launch, route the blockers to the right team and compare the impact of corrective action.')
st.caption('Portfolio demonstration · Fictional data · Your scenario is private to this browser session and resets on a new session.')
from launch_assurance.ui import render
from orchestration.header_definitions import render_header_definitions
render(show_title=False)
render_header_definitions()
with st.expander('About this prototype'):
    st.write('Built to demonstrate retail product operations: vendor and item setup, catalog content, buying controls, shipment delays and location-level inventory dependencies. Source validations use the included rule engines. Logistics and financial outcomes are deterministic simulations, not observed business results.')
    st.write('The downloadable source also contains the four local workbenches and 600-row synthetic datasets for end-to-end upload testing. This public view demonstrates the focused launch scenario; it does not connect to a live ERP or accept operational customer data.')


from launch_assurance.evaluation_ui import render as render_benchmark
render_benchmark()
