"""Display measured synthetic evidence without implying production accuracy."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st

def render():
 root=Path(__file__).resolve().parents[3]
 path=root/'benchmark/results.json'
 if not path.exists():return
 with st.expander('Validation benchmark evidence',expanded=False):
  report=json.loads(path.read_text(encoding='utf-8'))
  st.caption(report['basis'])
  st.dataframe(pd.DataFrame(report['results']),hide_index=True,width='stretch')
  st.download_button('Download benchmark report',path.read_bytes(),'synthetic-benchmark.json','application/json',key='benchmark_report')
  detail=root/'benchmark/record_results.csv'
  if detail.exists():st.download_button('Download record-level evidence',detail.read_bytes(),'benchmark-records.csv','text/csv',key='benchmark_records')
