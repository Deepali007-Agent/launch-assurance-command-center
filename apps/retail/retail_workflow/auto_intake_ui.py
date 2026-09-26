"""Concise local intake visibility. Polling does not execute validation in the browser."""
import json
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd
import streamlit as st
from .store import WorkflowStore
from .auto_intake import schema

@st.fragment(run_every=10)
def render():
    with st.expander('Automatic intake · local folder',expanded=False):
        st.caption('Sealed submissions are checked automatically while the local worker is running. Manual uploads remain available. Complete means checks finished, not approval granted.')
        runtime=Path(__file__).resolve().parents[3]/'local_intake'
        status=runtime/'status.json'
        try:
            state=json.loads(status.read_text(encoding='utf-8'))
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['heartbeat'])).total_seconds()
            st.write('Worker: '+('Monitoring' if age<120 else 'No recent heartbeat — worker stopped or a large batch is processing'))
            st.caption('Inbox: '+state['inbox'])
            errors=[r for r in state['submissions'] if r['Result']!='Checked']
            if errors:st.dataframe(pd.DataFrame(errors),hide_index=True)
        except (OSError,ValueError,KeyError):st.info('Worker has not reported yet. Start scripts/watch_intake.py locally.')
        store=WorkflowStore();schema(store)
        with store.connect() as db:rows=[dict(r) for r in db.execute('SELECT id,batch,state,stage,detail,updated FROM auto_jobs ORDER BY updated DESC')]
        if rows:
            st.dataframe(pd.DataFrame(rows).rename(columns={'state':'Status','stage':'Stage','detail':'Next step','batch':'Launch ID','updated':'Updated (UTC)','id':'Submission'}),hide_index=True)
            st.download_button('Download intake activity CSV',pd.DataFrame(rows).to_csv(index=False),'intake-activity.csv','text/csv')
            st.caption('Refresh the full page to select a newly created launch in Choose launch. Assigned owners and corrections appear in its Actions tab.')
            failed=[r['id'] for r in rows if r['state']=='Retry required']
            if failed:
                selected=st.selectbox('Interrupted submission',failed,help='An interrupted job retries automatically. Cancel it only to allow a new corrected submission; saved source evidence is retained.')
                if st.button('Cancel retry and allow corrected submission'):
                    with store.connect(True) as db:
                        db.execute("UPDATE auto_jobs SET state='Cancelled',stage='Cancelled',detail='Saved evidence retained; submit a new revision.' WHERE id=? AND state='Retry required'",(selected,))
                    st.rerun()
        else:st.caption('No automatic submissions yet.')
