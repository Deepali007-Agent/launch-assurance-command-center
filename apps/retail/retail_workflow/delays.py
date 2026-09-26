"""Item setup readiness and evidence-backed delay attribution, separate from approval gates."""
from datetime import datetime,timezone,date
from hashlib import sha256
import json
import pandas as pd
import streamlit as st

ORIGINS=['Not established','Vendor submission','Item Operations','Catalog Operations','Finance','External system','Other']
FINANCE_REASONS=['Not provided','Approval review pending','Payment terms unresolved','Outstanding dues reported','Other documented financial hold']

def tables(store):
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS delay_attribution(
          id INTEGER PRIMARY KEY AUTOINCREMENT,batch TEXT NOT NULL,delay_key TEXT NOT NULL,
          source TEXT NOT NULL,finance_reason TEXT NOT NULL,evidence_ref TEXT NOT NULL,
          actor TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL)""")

def _key(item,source,reason):
    return sha256(json.dumps([item['id'],item['version'],source['id'],source['version'],reason],ensure_ascii=False).encode()).hexdigest()

def actionability(source,team,reason,data_ready):
    """Use the existing gates, rather than inventing a different approval policy."""
    low=reason.lower()
    if 'acknowledgement' in low:
        active=bool(source['Execution eligible'])
        return ('Action needed now','Ready for simulated setup confirmation') if active else ('Waiting on another step','Current approval and source prerequisites must clear before setup confirmation')
    if 'approval' in low:
        active=bool(source['Approval eligible']) and not source['Approved']
        return ('Action needed now','Current source checks allow a human review') if active else ('Waiting on another step','Complete source validation/corrections before human review')
    if 'validation is missing' in low and source['kind']=='item' and not data_ready:
        return 'Waiting on another step','Complete mandatory item data before Catalog validation'
    if 'unresolved source requirements' in low:
        return 'Waiting on another step','Resolve the linked vendor source requirements listed separately'
    return 'Action needed now','Review and resolve this current requirement'


def analyze(store,batch,board=None):
    from .dashboard import evidence,source_status
    board=board if board is not None else store.board(batch)
    checks=evidence(store,batch)
    vendors={r['entity']:r for r in board if r['kind']=='vendor'}
    items=[r for r in board if r['kind']=='item'];pos=[r for r in board if r['kind']=='po']
    tables(store)
    with store.connect() as db:
        annotations={r['delay_key']:dict(r) for r in db.execute('SELECT * FROM delay_attribution WHERE batch=? ORDER BY id',(batch,))}
        timestamps={(r['request'],r['version']):r['created_at'] for r in db.execute('SELECT v.* FROM versions v JOIN requests r ON r.id=v.request WHERE r.batch=?',(batch,))}
    readiness=[];delays=[];today=datetime.now(timezone.utc).date()
    for item in items:
        payload=item['payload'];vendor=vendors.get(str(payload.get('vendor_id','')))
        linked=[r for r in pos if str(r['payload'].get('sku',r['payload'].get('SKU','')))==item['entity']]
        data_ready=source_status(item,checks,'Item intake')=='Clear'
        readiness.append({'SKU':item['entity'],'Item data ready':data_ready,'Catalog content clear':source_status(item,checks)=='Clear',
                          'Can proceed to simulated item setup':bool(item['Execution eligible']),
                          'Simulated item setup acknowledged':bool(item['ERP receipt']),
                          'Linked PO lines':len(linked),'PO lines eligible':sum(r['Execution eligible'] for r in linked)})
        reasons=[]
        for blocker in item['Blockers']:
            reason=blocker['reason'];team=blocker['team']
            source=vendor if vendor and (team in ('Finance','Vendor Operations') or reason.startswith('Vendor master')) else item
            reasons.append((source,team,reason))
        # Surface exact vendor source findings instead of only a generic linked prerequisite.
        if vendor:
            for blocker in vendor['Blockers']:
                if 'correction required' in blocker['reason'] or 'validation is missing' in blocker['reason']:
                    reasons.append((vendor,blocker['team'],blocker['reason']))
        seen=set()
        for source,team,reason in reasons:
            key=_key(item,source,reason)
            if key in seen:continue
            seen.add(key);annotation=annotations.get(key,{})
            origin=annotation.get('source','Not established')
            action_state,dependency=actionability(source,team,reason,data_ready)
            task_key=sha256(json.dumps([source['id'],source['version'],reason]).encode()).hexdigest()
            category='Finance approval' if team=='Finance' else 'Source correction' if any(t in reason.lower() for t in ['correction required','incomplete','unresolved source']) else 'Validation pending' if 'validation is missing' in reason else 'Setup acknowledgement' if 'acknowledgement' in reason else 'Item approval / workflow requirement'
            started=timestamps.get((source['id'],source['version']))
            age=round(max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(started)).total_seconds()/86400),1) if started else None
            owner=source['owner'] if source['team']==team and source['owner'] else 'Unassigned to this team'
            due=source['due'] if source['team']==team else ''
            delays.append({'Delay key':key,'SKU':item['entity'],'Item data ready':'Yes' if data_ready else 'No',
                'Delay category':category,'Requirement':reason,'Task ID':task_key,'Action status':action_state,'Dependency / next step':dependency,'SLA target':'Not configured','Actionable elapsed time':'Not measured','Completed TAT':'Not measured','Evidence source':('Vendor record' if source['kind']=='vendor' else 'Item / Catalog record'),
                'Source record':source['entity'],'Source version':source['version'],'Reason waiting':annotation.get('note') or 'Reason not recorded; only the pending requirement is known.',
                'Originating source':origin,'Accountable team':team,'Accountable owner':owner,
                'Assigned request team':source['team'],'Assigned request owner':source['owner'] or 'Unassigned',
                'Due':due or 'Not set','Overdue':bool(due and date.fromisoformat(due)<today),
                'Source version age (days)':age,'Linked PO lines':len(linked),
                'Recorded finance reason':annotation.get('finance_reason','Not provided'),
                'Evidence reference':annotation.get('evidence_ref','Not provided'),
                'Recorded by':annotation.get('actor','Not recorded'),'Attribution note':annotation.get('note',''),
                'Request ID':source['id'],'Request etag':source['etag']})
    return pd.DataFrame(readiness),pd.DataFrame(delays)

def record_attribution(store,batch,key,origin,finance_reason,reference,actor,note):
    if origin not in ORIGINS or finance_reason not in FINANCE_REASONS:raise ValueError('Choose a listed source and finance reason.')
    if not actor.strip() or not reference.strip():raise ValueError('A recorder and evidence reference are required; do not guess the cause.')
    before=store.token(batch)
    _,rows=analyze(store,batch)
    selected=rows[rows['Delay key']==key] if not rows.empty else rows
    if selected.empty:raise ValueError('This delay is no longer current. Refresh before recording evidence.')
    row=selected.iloc[0]
    if finance_reason!='Not provided' and row['Accountable team']!='Finance':raise ValueError('Finance evidence must be recorded against a Finance dependency.')
    # Serialize against source edits and hold/approval transitions.
    with store.connect(True) as db:
        current=db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE batch=?',(batch,)).fetchone()[0]
        request=store._get(db,row['Request ID'])
        if current!=before or request['etag']!=int(row['Request etag']):raise ValueError('Evidence changed. Refresh and retry.')
        db.execute('INSERT INTO delay_attribution(batch,delay_key,source,finance_reason,evidence_ref,actor,note,created_at) VALUES(?,?,?,?,?,?,?,?)',
                   (batch,key,origin,finance_reason,reference.strip(),actor.strip(),note.strip(),datetime.now(timezone.utc).isoformat()))
        store._event(db,batch,row['Request ID'],'Delay attribution recorded',actor.strip(),{'delay_key':key,'origin':origin,'finance_reason':finance_reason,'evidence_reference':reference.strip()})

def render(store,batch,key='item_delays',compact=False):
    readiness,rows=analyze(store,batch)
    st.subheader('Item readiness and dependencies',help='Separates mandatory item data, Catalog content and permission for simulated item setup. PO eligibility is evaluated separately.')
    if readiness.empty:st.info('No item requests in this batch.');return
    from .clarity import scope
    scope(store,batch)
    cols=st.columns(4)
    metrics=[('Item data ready',int(readiness['Item data ready'].sum()),'Current mandatory item-intake checks pass. This does not imply approval.'),
             ('Setup eligible',int(readiness['Can proceed to simulated item setup'].sum()),'All current item execution gates pass, including linked vendor approval and setup prerequisites. ERP execution is simulated.'),
             ('Data ready, waiting',int((readiness['Item data ready'] & ~readiness['Can proceed to simulated item setup']).sum()),'Mandatory fields pass but a source, approval or workflow dependency remains.'),
             ('Content clear',int(readiness['Catalog content clear'].sum()),'Current Catalog assessment has no warnings or critical findings; source clearance is not release permission.')]
    for col,(label,value,helptext) in zip(cols,metrics):col.metric(label,value,help=helptext)
    st.caption('Onboarding = mandatory setup data; Catalog = content checks; can proceed = current simulated item-setup gates. Launch readiness also depends on PO checks.')
    from orchestration.presentation import detail_table
    if rows.empty:st.success('No current item-setup blockers. PO and launch decisions remain separate.')
    else:
        st.subheader('Pending requirements before item setup',help='Current requirements affecting items; a single SKU or PO line may appear under several dependencies.')
        for state in ['Action needed now','Waiting on another step']:
            subset=rows[rows['Action status']==state]
            st.markdown('**'+state+'**')
            if subset.empty:
                st.caption('No current requirements in this group.')
                continue
            grouped=subset.groupby(['Delay category','Accountable team'],as_index=False).agg(**{'Distinct tasks':('Task ID','nunique'),'Affected unique SKUs':('SKU','nunique')})
            grouped['% of selected batch']=(100*grouped['Affected unique SKUs']/len(readiness)).round(1)
            grouped['SLA / elapsed time']='Not measured'
            st.dataframe(grouped.rename(columns={'Delay category':'Requirement','Accountable team':'Next action team'}),hide_index=True,width='stretch')
        st.caption('One vendor task may affect many SKUs. SKU counts overlap across requirements; task counts use the source record, version and requirement. Waiting steps are not active team delays. SLA targets and actionable start/completion timestamps are not yet measured; a due date alone is not an SLA.')
        st.caption('Catalog review can run in parallel with Finance once Catalog checks pass. Vendor setup confirmation waits for its own source checks and Finance approval. Item execution still requires all linked prerequisites.')
        if not compact:
            from .clarity import download_register
            download_register(store,batch,key+'_all_skus')
            common=rows.groupby(['Evidence source','Requirement'],as_index=False).agg(SKUs=('SKU','nunique')).sort_values('SKUs',ascending=False)
            detail_table(common,title='Requirement summary (counts only; SKU lists in the Excel register above)',export_key=key+'_requirements',context={'Batch':batch,'Scope':'Distinct SKUs per requirement; groups overlap.'},hide_index=True,width='stretch')
            team=st.selectbox('Filter next action team',['All teams']+sorted(rows['Accountable team'].unique()),key=key+'_team',help='Filter by the team required to resolve the dependency.')
            filtered=rows if team=='All teams' else rows[rows['Accountable team']==team]
            detail_table(filtered.drop(columns=['Request etag','Delay key']).rename(columns={'Accountable team':'Next action team','Accountable owner':'Next action owner','Originating source':'Documented issue origin','Delay category':'Pending requirement'}),title='Delay details and affected items',export_key=key+'_details',context={'Batch':batch,'Age definition':'Age of the current source revision, not proven time blocked.','Financial evidence':'User-recorded reference; not independently verified and not an approval.'},hide_index=True,width='stretch')
            with st.expander('Record why an approval or requirement is waiting'):
                st.caption('Example: Finance requested corrected payment terms (ticket FIN-104). If the cause is unknown, leave it unestablished. Recording a reason does not approve the request.')
                choices=filtered['Delay key'].tolist();labels={r['Delay key']:r['SKU']+' · '+r['Accountable team']+' · '+r['Requirement'] for r in filtered.to_dict('records')}
                selection=st.selectbox('Choose SKU and pending requirement',choices,format_func=lambda x:labels[x],key=key+'_select')
                with st.form(key+'_evidence_form'):
                    origin=st.selectbox('Where did the issue originate?',ORIGINS,help='Documented origin of the delay, not automatically the assigned team.')
                    finance=st.selectbox('Finance reason (only if documented)',FINANCE_REASONS,help='Select a financial reason only when supporting Finance evidence explicitly states it.')
                    reference=st.text_input('Supporting ticket or document',help='Document, ticket or approval reference supporting the attribution. Do not enter account credentials.')
                    actor=st.text_input('Recorded by',help='Named person providing this attribution; roles are not authenticated in this prototype.')
                    note=st.text_input('Reason waiting / next step',help='Brief explanation of the documented origin and next step.')
                    if st.form_submit_button('Save reason'):
                        try:record_attribution(store,batch,selection,origin,finance,reference,actor,note);st.success('Reason saved. Approval status is unchanged.');st.rerun()
                        except ValueError as exc:st.error(str(exc))
            st.caption('Use Actions & Approvals to assign/reassign the underlying request. An owner assigned to another team is not shown as the Finance owner.')
    if not compact:detail_table(readiness,title='Readiness by SKU',export_key=key+'_readiness',context={'Batch':batch},hide_index=True,width='stretch')
