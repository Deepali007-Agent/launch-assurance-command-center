"""Readable metrics and collapsed Excel-ready evidence tables."""
import hashlib
import json
from pathlib import Path
import subprocess
from contextlib import contextmanager
from uuid import uuid4
import pandas as pd
import streamlit as st

DEFINITIONS={
 'Commercial coverage':'Percentage of PO lines with valid positive cost and quantity plus an explicit currency.',
 'Commercial evidence coverage':'Percentage of PO lines with valid positive cost and quantity plus an explicit currency.',
 'Source actions':'Correction findings from the evaluated sources; one record can have more than one finding.',
 'Reconciliation':'Checks that source counts, identities and required launch evidence agree.',
 'Domain controls received':'Number of required domain assessments received; receipt alone does not establish release readiness.',
 'Evidence state':'Current freshness, completeness and human-review state of the selected evidence.',
 'Weighted control score':'Weighted source readiness diagnostic; a high score cannot override a release blocker.',
 'PO commitment':'Cost multiplied by PO quantity, counted once per line and kept separate by currency.',
 'Affected commitment':'PO commitment on lines affected by one or more findings, counted once per line.',
 'Retail value':'Regular retail price multiplied by quantity at full sell-through; not observed sales.',
 'Gross margin':'Regular retail less cost, multiplied by quantity; excludes taxes, returns and other costs.',
 'Scenario exposure':'Affected retail value or gross margin multiplied by the explicit sell-through assumption.',
 'Clear':'Records passing source checks; human approval remains a separate step.',
 'Warning':'Records needing review or correction without a critical source finding.',
 'Blocked':'Records with critical source findings preventing approval.',
}

def explained_metric(container,label,value,*args,**kwargs):
    explanation=kwargs.get('help') or DEFINITIONS.get(label)
    if not explanation: raise ValueError('Missing metric definition: '+str(label))
    container.metric(label,value,*args,**kwargs)
    container.caption(explanation)


from portable_excel import excel_bytes


def context_rows(context, prefix=''):
    rows=[]
    for key,value in context.items():
        label=prefix+str(key)
        if isinstance(value,dict):rows.extend(context_rows(value,label+'.'))
        else:rows.append({'Field':label,'Value':json.dumps(value) if isinstance(value,list) else value})
    return rows


@st.fragment
def detail_table(data, *, title='Detailed data', export_key=None, context=None, **kwargs):
    frame=pd.DataFrame(data)
    # Round-trip produces JSON nulls instead of nonfinite worksheet values.
    records=json.loads(frame.to_json(orient='records',date_format='iso'))
    for row in records:
        for column,value in row.items():
            if isinstance(value,str) and any(word in column.lower() for word in ['commitment','retail value','gross margin','revenue exposure']):
                try: row[column]=float(value)
                except ValueError: pass
    digest=hashlib.sha256(json.dumps(records,sort_keys=True).encode()).hexdigest()[:16]
    key=(export_key or title)+'_'+digest+'_'+hashlib.sha256(json.dumps(context,default=str,sort_keys=True).encode()).hexdigest()[:8]
    with st.expander(title+' · Excel download',expanded=False):
        st.dataframe(frame,**kwargs)
        st.caption('Prepare Excel, then select Download Excel. The table toolbar exports CSV only.')
        if st.button('Prepare Excel',key='prepare_'+key):
            try:
                with st.spinner('Preparing Excel…'):
                    st.session_state['xlsx_'+key]=excel_bytes({'Evidence':records,'Definitions':[{'Metric':k,'Explanation':v} for k,v in DEFINITIONS.items()], 'Context':[{'Field':'Export type','Value':'Fixed evidence snapshot; re-export after revalidation.'}]+context_rows(context or {})})
            except (ValueError,OSError,subprocess.TimeoutExpired) as error:st.error(str(error))
        if 'xlsx_'+key in st.session_state:
            st.download_button('Download Excel',st.session_state['xlsx_'+key],file_name=(export_key or 'retail-evidence')+'-'+digest[:8]+'.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='download_'+key,on_click='ignore')


def composition_chart(data, category, value, color, *, sort=None, domain=None, colors=None, grouped=False, within_category=False):
    """Vertical values and explicit composition labels; zero totals stay unavailable."""
    import altair as alt
    frame=pd.DataFrame(data).copy()
    total=frame.groupby(category)[value].transform('sum') if within_category else frame[value].sum()
    frame['Share']=frame[value].div(total.replace(0,float('nan')) if within_category else (total or float('nan')))
    frame['Label']=[f'{v:,.0f} ({p:.1%})' if pd.notna(p) else f'{v:,.0f} (n/a)' for v,p in zip(frame[value],frame['Share'])]
    enc=dict(x=alt.X(category+':N',sort=sort or 'ascending',title=None,axis=alt.Axis(labelAngle=0,labelLimit=140)),
             y=alt.Y(value+':Q',title=value,scale=alt.Scale(zero=True),axis=alt.Axis(tickMinStep=1)),
             tooltip=[category,color,alt.Tooltip(value+':Q',format=',.2f'),alt.Tooltip('Share:Q',format='.1%')])
    if grouped:enc['xOffset']=alt.XOffset(color+':N',sort=domain or 'ascending')
    base=alt.Chart(frame).encode(**enc)
    color_enc=alt.Color(color+':N',scale=alt.Scale(domain=domain,range=colors)) if domain else alt.Color(color+':N')
    bars=base.mark_bar().encode(color=color_enc)
    labels=base.mark_text(dy=-9,fontSize=11,color='#f0f2f6').encode(text='Label:N')
    return (bars+labels).properties(height=230).configure_view(stroke=None)



