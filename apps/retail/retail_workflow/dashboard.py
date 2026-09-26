"""Shared decision dashboards: current ledger evidence, never invented growth."""
from collections import Counter
from datetime import datetime
from html import escape
import json
import math
import pandas as pd
import altair as alt
import streamlit as st

COLORS=['#20c8bd','#ff737b','#ffca61','#8c9db8']
ENGINES={'vendor':'Vendor','item':'Catalog','po':'PO'}

def evidence(store,batch):
    with store.connect() as db:
        rows=db.execute("SELECT a.*,r.entity,r.kind,r.payload FROM assessments a JOIN requests r ON r.id=a.request AND r.version=a.version WHERE r.batch=?",(batch,)).fetchall()
    return {(r['request'],r['engine']):dict(r) for r in rows}

def source_status(row,assessments,engine=None):
    a=assessments.get((row['id'],engine or ENGINES[row['kind']]))
    return a['status'] if a else 'Not assessed'

def po_state(row,linked_correction=False):
    if row['Execution eligible']:return 'Eligible'
    reasons=' '.join(b['reason'].lower() for b in row['Blockers'])
    if linked_correction or any(term in reasons for term in ['correction required','unresolved source','incomplete','does not match','must be supplied','has not been onboarded','linked vendor is missing']):return 'Correction required'
    return 'Awaiting prerequisites'

def readiness(board,checks):
    vendors={r['entity']:r for r in board if r['kind']=='vendor'}
    items={r['entity']:r for r in board if r['kind']=='item'}
    result=Counter()
    for r in board:
        if r['kind']!='po':continue
        p=r['payload'];vendor=vendors.get(str(p.get('vendor_id',p.get('Vendor ID',''))));item=items.get(str(p.get('sku',p.get('SKU',''))))
        correction=(vendor is not None and source_status(vendor,checks)=='Blocked') or (item is not None and (source_status(item,checks)=='Blocked' or source_status(item,checks,'Item intake')=='Blocked'))
        result[po_state(r,correction)]+=1
    return result


def history(store,batch):
    # Reconstruct source statuses at actual completed-submission timestamps.
    # This is source validation history, not a reconstruction of historical approvals.
    with store.connect() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='auto_jobs'").fetchone()
        checkpoints=[dict(r) for r in db.execute("SELECT id,updated FROM auto_jobs WHERE batch=? AND state IN ('Complete','Needs correction') ORDER BY updated",(batch,))] if exists else []
        versions=[dict(r) for r in db.execute('SELECT v.*,r.kind FROM versions v JOIN requests r ON r.id=v.request WHERE r.batch=? ORDER BY v.version',(batch,))]
        checks=[dict(r) for r in db.execute('SELECT a.* FROM assessments a JOIN requests r ON r.id=a.request WHERE r.batch=?',(batch,))]
    result=[]
    for number,point in enumerate(checkpoints[-8:],1):
        current={}
        for v in versions:
            if v['created_at']<=point['updated']:current[v['request']]=v
        available={(a['request'],a['version'],a['engine']):a for a in checks if a['created_at']<=point['updated']}
        for kind,engine in list(ENGINES.items())+[('item','Item intake')]:
            members=[v for v in current.values() if v['kind']==kind]
            assessed=[available.get((v['request'],v['version'],engine)) for v in members]
            clear=sum(a is not None and a['status']=='Clear' for a in assessed)
            blocked=sum(a is not None and a['status']=='Blocked' for a in assessed)
            findings=sum(len(json.loads(a['findings'])) for a in assessed if a)
            result.append({'Run':f'Run {number}','Domain':engine,'Pass rate':100*clear/len(members) if members else 0,'Records':len(members),'Critical records':blocked,'Findings':findings,'Time':point['updated']})
    return pd.DataFrame(result)

def groups(board,kind=None):
    pending=[r for r in board if (not kind or r['kind']==kind) and not r['Execution eligible']]
    out={}
    for r in pending:
        key=(r['Next team'],r['Next action'])
        group=out.setdefault(key,{'Action':r['Next action'],'Team':r['Next team'],'Records':0,'owners':set(),'dues':[]})
        group['Records']+=1;group['owners'].add(r['owner'] if r['team']==r['Next team'] and r['owner'] else 'Unassigned to this team')
        if r['due'] and r['team']==r['Next team']:group['dues'].append(r['due'])
    result=[]
    for g in sorted(out.values(),key=lambda x:-x['Records']):
        result.append({'#':len(result)+1,'Action':g['Action'],'Team':g['Team'],'Records':g['Records'],'Owner':', '.join(sorted(g['owners'])),'Due':min(g['dues']) if g['dues'] else 'Not set'})
    return pd.DataFrame(result)

def theme():
    st.markdown("""<style>
    .stApp {background:#0b1421;color:#eef6ff}
    .block-container{max-width:1600px;padding-top:1.7rem}
    h1,h2,h3{color:#edf6ff;letter-spacing:-.025em}
    [data-testid="stTabs"] [role="tab"][aria-selected="true"]{color:#20d9ce}
    [data-testid="stTabs"] [data-baseweb="tab-highlight"]{background:#20c8bd}
    [data-testid="stVerticalBlock"]:has(>.dash-kpis){gap:0} .dash-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:12px 0 18px}
    .dash-kpi{background:linear-gradient(120deg,#142a3b,#172536);border:1px solid #294254;border-radius:10px;padding:22px}
    .dash-label{font-size:15px;color:#d9e5f4}.dash-value{font-size:38px;font-weight:750;margin:8px 0}.dash-foot{font-size:13px;color:#9bb0c9}
    .dash-banner{background:#10313b;border:1px solid #1fb7b6;border-radius:10px;padding:16px 20px;margin:10px 0 18px;color:#d7f9f5}
    .dash-context{border:1px solid #294254;border-radius:9px;padding:12px 16px;color:#b8cce0;background:#132233}
    .dash-flow{display:flex;gap:8px;align-items:center;justify-content:space-between;padding:14px;background:#13283a;border-radius:9px;margin:14px 0;font-size:14px;color:#bff8f3}
    div[data-testid="stVerticalBlockBorderWrapper"]>div{border-color:#294254!important;border-radius:10px!important}
    @media(max-width:800px){.dash-kpis{grid-template-columns:repeat(2,1fr)}.dash-flow{flex-wrap:wrap}.dash-value{font-size:28px}}
    </style>""",unsafe_allow_html=True)

def cards(values):
    html='<div class="dash-kpis">'
    for i,(label,value,foot,helptext) in enumerate(values):
        html+=f'<div class="dash-kpi"><div class="dash-label">{escape(label)} <span title="{escape(helptext,quote=True)}">ⓘ</span></div><div class="dash-value" style="color:{COLORS[(i-1)%4] if i else "#ffffff"}">{escape(str(value))}</div><div class="dash-foot">{escape(foot)}</div></div>'
    st.markdown(html+'</div>',unsafe_allow_html=True)

def chart_style(chart):
    return chart.properties(height=230).configure(background='transparent').configure_view(stroke=None).configure_axis(labelColor='#c3d4e7',titleColor='#9cb1c9',gridColor='#26394b',labelFontSize=12,titleFontSize=12).configure_legend(labelColor='#c3d4e7',titleColor='#c3d4e7',orient='bottom')

def bars(data,label='Group',value='Records',percent=True):
    frame=pd.DataFrame(data)
    if frame.empty or not frame[value].sum():st.caption('No findings in this scope.');return
    total=frame[value].sum();frame['Label']=[f'{n:,} · {n/total:.0%}' if percent else f'{n:,}' for n in frame[value]]
    base=alt.Chart(frame).encode(x=alt.X(label+':N',sort=None,title=None,axis=alt.Axis(labelAngle=0,labelLimit=135)),y=alt.Y(value+':Q',title=value,scale=alt.Scale(zero=True)),tooltip=[label,value,'Label'])
    plot=base.mark_bar(cornerRadiusTopLeft=3,cornerRadiusTopRight=3).encode(color=alt.Color(label+':N',scale=alt.Scale(range=COLORS),legend=None))
    st.altair_chart(chart_style(plot+base.mark_text(dy=-10,color='#eef6ff').encode(text='Label:N')),width='stretch')

def donut(counts):
    frame=pd.DataFrame([{'Status':k,'Records':v} for k,v in counts.items() if v])
    if frame.empty:st.caption('No pending records.');return
    total=frame.Records.sum();frame['Composition']=frame.apply(lambda x:f'{x.Status}: {x.Records} ({x.Records/total:.1%})',axis=1)
    chart=alt.Chart(frame).mark_arc(innerRadius=65,outerRadius=95).encode(theta='Records:Q',color=alt.Color('Composition:N',scale=alt.Scale(range=COLORS),legend=alt.Legend(title=None)),tooltip=['Status','Records','Composition'])
    st.altair_chart(chart_style(chart),width='stretch')

def trend(frame,domains):
    if frame.empty or frame.Run.nunique()<2:
        st.info('Trend available after two completed automatic submissions. No historical values are assumed.');return
    subset=frame[frame.Domain.isin(domains)]
    chart=alt.Chart(subset).mark_line(point=True,strokeWidth=3).encode(x=alt.X('Run:N',axis=alt.Axis(labelAngle=0),title=None),y=alt.Y('Pass rate:Q',scale=alt.Scale(domain=[0,100]),title='Source-clear records (%)'),color=alt.Color('Domain:N',scale=alt.Scale(range=COLORS)),tooltip=['Run','Domain',alt.Tooltip('Pass rate:Q',format='.1f'),'Records','Time'])
    st.altair_chart(chart_style(chart),width='stretch')
    st.caption('Saved submission checkpoints; source-clear rate, not first-pass accuracy or approval rate.')

def causes(rows,assessments):
    counts=Counter()
    for r in rows:
        a=assessments.get((r['id'],ENGINES[r['kind']]))
        if a:
            for f in set(json.loads(a['findings'])):
                if str(f).strip().lower() not in ('none','null',''):
                    counts[str(f).split(':')[0][:65]]+=1
    return [{'Group':k,'Records':v} for k,v in counts.most_common(5)]

def assistant(board,frame):
    st.subheader('Ask Retail Intelligence',help='Read-only explanations from this selected batch. No approvals or source data are changed.')
    st.caption('Evidence-based lookup · no generative model connected')
    question=st.text_input('Ask about this launch',placeholder='Why are PO lines blocked?',key='dash_question')
    topic=st.selectbox('Focus',['Current blockers','Finance actions','Changes between runs','Eligible subset'],key='dash_topic')
    if st.button('Explain current evidence',key='dash_explain'):
        pos=[r for r in board if r['kind']=='po'];ready=sum(r['Execution eligible'] for r in pos)
        query=question.lower()
        if 'finance' in query or topic=='Finance actions':
            rows=[r for r in pos if any(b['team']=='Finance' for b in r['Blockers'])]
            st.write(f'{len(rows):,} PO lines have a Finance dependency. Review current vendor versions in Onboarding → Actions & Approvals. This response does not approve them.')
        elif 'change' in query or topic=='Changes between runs':
            if frame.empty or frame.Run.nunique()<2:st.info('Two completed submissions are needed for a comparison.')
            else:st.dataframe(frame[['Run','Domain','Critical records','Findings']],hide_index=True)
        elif 'eligible' in query or topic=='Eligible subset':st.write(f'{ready:,} of {len(pos):,} PO lines satisfy current execution gates. Physical ERP execution is not connected.')
        else:
            st.write(f'{len(pos)-ready:,} of {len(pos):,} PO lines still need action. The leading current requirements are:')
            st.dataframe(groups(board,'po').head(3),hide_index=True,width='stretch')
        st.caption('Source: current shared request versions and completed intake checkpoints. Questions outside these supported topics require inspecting Evidence.')

def render(store,batch,view):
    theme();board=store.board(batch);checks=evidence(store,batch);hist=history(store,batch)
    vendors=[r for r in board if r['kind']=='vendor'];items=[r for r in board if r['kind']=='item'];pos=[r for r in board if r['kind']=='po']
    name=next((b['name'] for b in store.batches() if b['id']==batch),batch)
    title={'retail':'Retail Intelligence','onboarding':'Onboarding Intelligence','catalog':'Catalog Intelligence','po':'PO / Buying Ops Intelligence'}[view]
    heading,chat=st.columns([3,1])
    with heading:st.subheader('Dashboard' if view!='retail' else title+' Dashboard',help='Current batch evidence, with source validation and approval dependencies shown separately.')
    if view=='retail':
        with chat:
            with st.popover('Ask Retail Intelligence',help='Open read-only explanations grounded in this selected batch.'):
                assistant(board,hist)
    st.markdown(f'<div class="dash-context">{escape(name)} &nbsp; • &nbsp; Connected batch &nbsp; • &nbsp; INR amounts only &nbsp; • &nbsp; Local prototype</div>',unsafe_allow_html=True)
    from . import clarity
    import importlib
    importlib.reload(clarity)
    from .clarity import stage_guide,download_register
    stage_guide(view)
    with st.expander('Download SKU and team action register'):
        download_register(store,batch,'dashboard_register_'+view)
    percent=lambda n,d:f'{n/d:.0%}' if d else 'No records'
    counts=readiness(board,checks)
    if view in ('retail','po'):
        cards([('PO lines assessed',len(pos),'Current batch','Distinct versioned PO lines, not unique SKUs.'),('Eligible to proceed',counts['Eligible'],percent(counts['Eligible'],len(pos)),'All current execution gates satisfied; actual execution is simulated.'),('Correction required',counts['Correction required'],percent(counts['Correction required'],len(pos)),'At least one source or linked identity correction is required.'),('Awaiting prerequisites',counts['Awaiting prerequisites'],percent(counts['Awaiting prerequisites'],len(pos)),'Other holds, validation, approval or simulated setup prerequisites remain.')])
        msg=f"{counts['Eligible']:,} of {len(pos):,} PO lines meet execution gates. {len(pos)-counts['Eligible']:,} require correction or prerequisites."
        st.markdown('<div class="dash-banner"><b>Combined decision: '+('Review eligible subset' if counts['Eligible'] else 'Hold execution')+'</b> &nbsp; '+escape(msg)+'</div>',unsafe_allow_html=True)
    elif view=='onboarding':
        vc=sum(source_status(r,checks)=='Clear' for r in vendors);ic=sum(source_status(r,checks,'Item intake')=='Clear' for r in items)
        eligible=sum(r['Execution eligible'] for r in items)
        waiting=sum(source_status(r,checks,'Item intake')=='Clear' and not r['Execution eligible'] for r in items)
        cards([('Item records',len(items),f'{len(vendors)} linked vendor records','Unique item requests in this batch.'),('Item data ready',ic,percent(ic,len(items)),'Mandatory item-intake checks pass; content and approvals are separate.'),('Can proceed to item setup',eligible,percent(eligible,len(items)),'All current item execution gates pass; ERP setup remains simulated.'),('Data ready, still waiting',waiting,percent(waiting,len(items)),'Mandatory data is complete but a content, approval or setup prerequisite remains.')])
        st.markdown(f'<div class="dash-banner"><b>Next handoff:</b> {ic:,} items pass mandatory setup checks; {len(items)-ic:,} require assessment or correction. Catalog assessment and human approval remain separate.</div>',unsafe_allow_html=True)
    else:
        states=Counter(source_status(r,checks) for r in items)
        cards([('SKUs evaluated',len(items)-states['Not assessed'],f"{states['Not assessed']} awaiting checks",'Current-version Catalog assessments only.'),('Content checks passed',states['Clear'],percent(states['Clear'],len(items)),'No current Catalog warnings or critical findings.'),('Warning-only',states['Review'],percent(states['Review'],len(items)),'Warnings need review.'),('Critical gaps',states['Blocked'],percent(states['Blocked'],len(items)),'Critical Catalog findings prevent progression.')])
        st.markdown(f'<div class="dash-banner"><b>Catalog recommendation:</b> Resolve {states["Blocked"]:,} blocked SKUs and review {states["Review"]:,} warning-only SKUs. Content clearance does not authorize a PO.</div>',unsafe_allow_html=True)
    if view=='retail':
        st.markdown('<div class="dash-flow">① Intake → ② Agent checks → ③ Combined decision → ④ Team actions → ⑤ Human review</div>',unsafe_allow_html=True)
    cols=st.columns(3)
    with cols[0],st.container(border=True):
        st.subheader('Validation trend',help='Source-clear percentage at saved automatic-submission completion times; warnings are not source-clear.')
        trend(hist, ['Vendor','Catalog','PO'] if view=='retail' else ['Vendor','Item intake'] if view=='onboarding' else ['Catalog'] if view=='catalog' else ['PO'])
    with cols[1],st.container(border=True):
        if view=='onboarding':
            st.subheader('Vendor review status',help='Current vendor workflow status, separate from item counts.')
            donut(Counter(r['Status'] for r in vendors))
        elif view=='catalog':
            st.subheader('Content gap composition',help='Finding occurrences by requirement; one SKU can contribute to multiple requirements.')
            bars(causes(items,checks));st.caption('Share of displayed findings, not unique SKU composition.')
        elif view=='po':
            st.subheader('Margin distribution',help='Calculated (retail minus cost) / retail for valid INR PO lines; this chart does not define a policy floor.')
            margins=Counter();excluded=0
            for r in pos:
                p=r['payload']
                try:
                    cost=float(p.get('Cost'));retail=float(p.get('Reg Retail'))
                    if p.get('currency')!='INR' or not all(math.isfinite(v) and v>0 for v in [cost,retail]):raise ValueError()
                    m=100*(retail-cost)/retail
                    margins['<30%' if m<30 else '30–39%' if m<40 else '40–49%' if m<50 else '50%+']+=1
                except (TypeError,ValueError):excluded+=1
            bars([{'Group':k,'Records':margins[k]} for k in ['<30%','30–39%','40–49%','50%+']]);st.caption(f'{excluded} lines excluded for missing/invalid values or currency.')
        else:
            st.subheader('PO readiness',help='Mutually exclusive classification using all current execution blockers.')
            bars([{'Group':k,'Records':counts[k]} for k in ['Eligible','Correction required','Awaiting prerequisites']])
    with cols[2],st.container(border=True):
        if view=='catalog':
            st.subheader('Vendor content consistency',help='Current source-clear SKU share by vendor; historical consistency needs comparable saved populations.')
            values={}
            for r in items:
                vendor=str(r['payload'].get('vendor_id','Unknown'));g=values.setdefault(vendor,[0,0]);g[0]+=1;g[1]+=source_status(r,checks)=='Clear'
            data=pd.DataFrame([{'Vendor':v,'Scope':'Current','Clear %':100*b/a,'SKUs':a} for v,(a,b) in sorted(values.items(),key=lambda x:(x[1][1]/x[1][0],x[0]))[:6]])
            if not data.empty:
                chart=alt.Chart(data).mark_rect().encode(x=alt.X('Scope:N',title=None),y=alt.Y('Vendor:N',title=None),color=alt.Color('Clear %:Q',scale=alt.Scale(domain=[0,100],range=['#723846','#20c8bd'])),tooltip=['Vendor','Clear %','SKUs'])
                st.altair_chart(chart_style(chart),width='stretch');st.caption('Six lowest source-clear rates in the current batch; no historical trend inferred.')
        elif view=='onboarding':
            st.subheader('Item setup completeness',help='Mandatory item assessment, independent of Catalog content and approval.')
            c=sum(source_status(r,checks,'Item intake')=='Clear' for r in items)
            bars([{'Group':'Complete','Records':c},{'Group':'Needs checks / correction','Records':len(items)-c}])
        else:
            st.subheader('Next team to act',help='One primary next team per ineligible PO line. Other dependencies may also apply.')
            donut(Counter(r['Next team'] for r in pos if not r['Execution eligible']))
    left,right=st.columns([1,2])
    with left,st.container(border=True):
        st.subheader('Correction progress',help='Compare the count of source findings at completed submission checkpoints; a net decrease does not prove individual findings were resolved.')
        if hist.empty or hist.Run.nunique()<2:st.info('Needs two saved validation checkpoints.')
        else:
            subset=hist[hist.Domain.isin(['Vendor','Catalog','PO'])] if view=='retail' else hist[hist.Domain.isin(['Vendor','Item intake'] if view=='onboarding' else ['Catalog'] if view=='catalog' else ['PO'])]
            values=subset.groupby('Run',sort=False).Findings.sum()
            bars([{'Group':k,'Findings':int(v)} for k,v in values.items()],value='Findings',percent=False)
            delta=int(values.iloc[0]-values.iloc[-1]);st.caption(f'Net change: {delta:+,} fewer findings across displayed checkpoints. Counts can overlap records.')
    with right,st.container(border=True):
        st.subheader('Shared decisions across teams' if view=='retail' else 'Top Recommended Actions',help='Prioritized by affected record count. Current action, accountable team, owner and due date come from the shared ledger.')
        scope='po' if view in ('retail','po') else 'item' if view=='catalog' else None
        scoped=board if view!='onboarding' else [r for r in board if r['kind'] in ('vendor','item')]
        actions=groups(scoped,scope)
        if actions.empty:st.success('No pending execution prerequisites in this scope.')
        else:
            st.dataframe(actions.head(3),hide_index=True,width='stretch')
            from orchestration.presentation import detail_table
            detail_table(actions,title='View all actions',export_key='dashboard_'+view,context={'Batch':batch,'View':view},hide_index=True,width='stretch')
    if view in ('retail','onboarding','catalog'):
        with st.expander('Why are ready items still waiting?',expanded=False):
            from .delays import render as render_delays
            render_delays(store,batch,key='dash_delays_'+view,compact=True)
    st.caption('Current local evidence • INR values are not currency-converted • Human approvals required • ERP handoff simulated')
