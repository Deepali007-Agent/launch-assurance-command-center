"""Shared plain-language workflow views; never relax execution gates."""
from collections import Counter
import re
import pandas as pd
import streamlit as st

ROLES=[
 ('Vendor Onboarding','Is vendor information complete?','Vendor Operations','Finance reviews the vendor; Vendor Operations confirms simulated vendor setup.'),
 ('Item Onboarding','Can we prepare this SKU for setup?','Item Onboarding','Mandatory attributes and vendor linkage; eligible records enter Catalog without another initial upload.'),
 ('Catalog Intelligence','Is content ready for the selling channel?','Catalog Operations','Enrichment, content checks, item approval and simulated item setup; Finance can remain pending during enrichment.'),
 ('PO / Buying Ops','Can this purchase request proceed?','Buying Operations','Validate vendor + category + gender + SKU, commercial rules and upstream approvals/setup.'),
 ('Retail Intelligence','What can proceed and who acts next?','Cross-team coordination','Connect requirements to launch impact; track actions and revalidation. Human approvals remain separate.')]

def clean(value):
    text=str(value)
    for bad,good in [('Â·',' · '),('â€”',' — '),('â€¦','…')]:text=text.replace(bad,good)
    return re.sub('<[^>]+>','',text)

def stage_guide(view):
    label={'onboarding':'Item Onboarding','catalog':'Catalog Intelligence','po':'PO / Buying Ops','retail':'Retail Intelligence'}[view]
    row=next(r for r in ROLES if r[0]==label)
    st.caption(row[1]+' '+row[3])
    with st.expander('Workflow and team responsibilities'):
        st.dataframe(pd.DataFrame(ROLES,columns=['Stage','Question answered','Responsible team','Responsibility / handoff']),hide_index=True,width='stretch')
        st.caption('A receiving team owns the next action; it is not automatically the source of the issue. Approvals and ERP acknowledgements are separate; ERP actions are simulated.')

def primary_step(row,checks):
    from .dashboard import source_status
    if row['ERP receipt']:return 'Setup acknowledged (simulated)' if row['kind']!='po' else 'PO acknowledged (simulated)'
    if row['Execution eligible']:return 'Eligible for item setup' if row['kind']=='item' else 'Eligible for simulated execution'
    if row['kind']=='item' and source_status(row,checks,'Item intake')!='Clear':return 'Needs mandatory-data assessment / correction'
    if source_status(row,checks)=='Not assessed':return 'Awaiting '+{'item':'Catalog','vendor':'vendor','po':'PO'}[row['kind']]+' validation'
    if source_status(row,checks)=='Blocked':return 'Needs '+{'item':'Catalog content','vendor':'vendor data','po':'PO data'}[row['kind']]+' correction'
    reasons=' '.join(b['reason'].lower() for b in row['Blockers'])
    if 'held or returned' in reasons:return 'On hold / returned for review'
    if any(x in reasons for x in ['unresolved source','missing from this batch','does not match','must be supplied','has not been onboarded']):return 'Needs linked-record correction'
    if 'finance approval' in reasons:return 'Awaiting Finance approval'
    if 'vendor master' in reasons:return 'Awaiting vendor setup confirmation'
    if 'content, setup or vendor prerequisites' in reasons:return 'Awaiting linked item prerequisites'
    if 'human approval' in reasons or 'catalog approval' in reasons:return 'Awaiting '+{'item':'Catalog','vendor':'Finance','po':'Buying'}[row['kind']]+' approval'
    if 'item setup' in reasons:return 'Awaiting item setup confirmation'
    return 'Awaiting workflow prerequisites'

def scope(store,batch):
    items=store.requests(batch,'item')
    counts=Counter(re.sub(r'-[0-9]+$','',r['entity']) for r in items)
    st.caption(f'Selected batch: {len(items):,} unique SKUs. Counts refer to current versions; uploads with new IDs add records.')
    if len(counts)<=8 and len(counts)>1:
        st.caption('SKU ID groups: '+ ' · '.join(f'{k}: {v:,}' for k,v in sorted(counts.items()))+'. ID groups identify naming patterns, not business categories.')

def workbook_sheets(store,batch):
    from .delays import analyze
    from .dashboard import evidence
    board=store.board(batch);checks=evidence(store,batch);ready,requirements=analyze(store,batch,board)
    overview=[];assignments=[];po_requirements=[]
    readiness={r['SKU']:r for r in ready.to_dict('records')}
    for row in board:
        p=row['payload'];sku=row['entity'] if row['kind']=='item' else str(p.get('sku',p.get('SKU','')))
        assignments.append({'Request ID':row['id'],'Record type':row['kind'],'Record':row['entity'],'SKU':sku,'Assigned team':row['team'],'Assigned owner':row['owner'] or 'Unassigned','Next action team':row['Next team'],'Next action owner':row['owner'] if row['team']==row['Next team'] and row['owner'] else 'Unassigned to this team','Due':row['due'] or 'Not set','Work status':row['work_status'],'Primary next step':primary_step(row,checks),'Next action':clean(row['Next action'])})
        if row['kind']=='po':
            for blocker in row['Blockers']:
                po_requirements.append({'PO line':row['entity'],'SKU':sku,'Next action team':blocker['team'],'Requirement':clean(blocker['reason'])})
        if row['kind']=='item':
            overview.append(dict(readiness.get(sku,{'SKU':sku}),Vendor=p.get('vendor_id',''),**{'Primary next step':primary_step(row,checks),'Next action team':row['Next team'],'Next action':clean(row['Next action'])}))
    detail=requirements.drop(columns=['Delay key','Request etag'],errors='ignore').rename(columns={'Delay category':'Pending requirement','Accountable team':'Next action team','Accountable owner':'Next action owner','Originating source':'Documented issue origin'})
    if not detail.empty:detail['Requirement']=detail.Requirement.map(clean)
    summary=[]
    if not detail.empty:
        summary=detail.groupby(['Action status','Pending requirement','Next action team'],as_index=False).agg(**{'Distinct tasks':('Task ID','nunique'),'Affected unique SKUs':('SKU','nunique')}).to_dict('records')
    sheets={'SKU overview':overview,'Requirements':detail.to_dict('records'),'Assignments':assignments,'Summary':summary,'PO requirements':po_requirements}
    if not detail.empty:
        for team,frame in detail.groupby('Next action team'):sheets[team]=frame.to_dict('records')
    sheets['Read me']=[{'Definition':'Scope','Meaning':f'Batch {batch}; {len(overview)} unique item IDs. Team and requirement counts overlap; do not sum them.'},{'Definition':'Pending versus overdue','Meaning':'Pending requirements are not necessarily delayed. Overdue requires a recorded past due date.'},{'Definition':'Approval reasons','Meaning':'Not recorded means unknown. User-supplied evidence is not independently verified and never grants approval.'},{'Definition':'Primary next step','Meaning':'One state per record: receipt, eligibility, own data/checks, hold, linked corrections, Finance, vendor setup, item prerequisites, approval, other. All concurrent requirements remain in Requirements.'}]
    return sheets

def download_register(store,batch,key):
    import importlib, portable_excel
    excel_bytes=importlib.reload(portable_excel).excel_bytes
    st.download_button('Download all SKUs, requirements and assignments — Excel',lambda: excel_bytes(workbook_sheets(store,batch)),file_name='sku-action-register-'+batch+'.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key=key,on_click='ignore',help='All SKUs in the selected batch, all outstanding item requirements, request assignments and team-specific sheets. Includes ready items.')
