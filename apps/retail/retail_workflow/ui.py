"""Compact shared controls used by each workbench and the parent workspace."""
import html
import json
import re
from pathlib import Path
import pandas as pd
import streamlit as st
from .store import WorkflowStore, TEAMS, ROOT, Conflict


def records(frame):
    return json.loads(pd.DataFrame(frame).to_json(orient='records',date_format='iso'))


def batch_selector(stage,allow_create=False):
    _definitions()
    store=WorkflowStore()
    if st.button('Refresh available batches',key='refresh_batches_'+stage,help='Reload batches created by automatic intake or another workbench.'):
        st.rerun()
    batches=store.batches();names={b['id']:b['name'] for b in batches}
    options=['']+list(names)
    if st.session_state.get('connected_batch') not in options:st.session_state.pop('connected_batch',None)
    if len(names)==1 and not st.session_state.get('connected_batch'):
        st.session_state['connected_batch']=next(iter(names))
    batch=st.selectbox('Shared workflow batch',options,format_func=lambda value:names.get(value,'Select a batch'),
                       key='connected_batch',help='Select the same batch in all workbenches to use one versioned request history.')
    if allow_create:
        with st.expander('Start a workflow batch',expanded=not batches):
            with st.form('new_shared_batch_'+stage):
                name=st.text_input('Batch / launch name',help='A recognizable name for this set of vendor, item and buying requests.')
                actor=st.text_input('Created by',help='Your name, recorded in the local audit history.')
                if st.form_submit_button('Create shared batch'):
                    try:
                        store.create_batch(name,actor)
                        st.success('Batch created. Select it above to begin.');st.rerun()
                    except ValueError as exc:st.error(str(exc))
    if not batch:
        st.info('Select an existing batch above to review its records. No re-upload is needed.' if batches else 'No shared batches yet. Submit a folder through automatic intake or create a batch in Onboarding.')
    return store,batch


def save_onboarding(store,batch,vendors,assessments,items,actor):
    by_vendor={}
    for row in records(assessments):
        identifier=str(row['vendor_id']).strip()
        outcome=by_vendor.setdefault(identifier,{'status':'Clear','findings':[]})
        if row.get('severity')=='Critical':outcome['status']='Blocked'
        elif row.get('severity')=='Warning' and outcome['status']=='Clear':outcome['status']='Review'
        for finding in row.get('findings',[]):
            message=finding.get('message') or finding.get('issue') or finding.get('code') or str(finding)
            if finding.get('field'):message=str(finding['field'])+': '+message
            if finding.get('how_to_fix'):message+=' — '+str(finding['how_to_fix'])
            outcome['findings'].append(html.unescape(re.sub('<[^>]+>','',message)))
    return store.ingest_onboarding(batch,records(vendors),records(items),by_vendor,actor)


def process_catalog_queue(store,batch,repo):
    from catalog_operations.ingestion import ingest_dataframe
    from catalog_operations.services import process_upload
    queue=store.catalog_queue(batch)
    if not queue:return 0
    try:
        frame=pd.DataFrame([row['payload'] for row in queue])
        check=ingest_dataframe(frame)
        if check.errors:raise ValueError('; '.join(e.message for e in check.errors[:8]))
        result=process_upload(frame,'Shared batch '+batch,repo,replace_catalog=False)
        if result.ingestion.errors:raise ValueError('; '.join(e.message for e in result.ingestion.errors[:8]))
        output={}
        for assessments,decision in result.evaluations:
            output[decision.sku]={'status':'Blocked' if decision.critical_blockers else 'Review' if decision.warnings else 'Clear',
                                  'findings':[str(row.get('message') or row.get('code') or row) for row in decision.critical_blockers+decision.warnings]}
        store.complete_catalog(queue,output)
        return len(queue)
    except Exception as exc:
        store.fail_catalog(queue,str(exc));raise


def catalog_intake(store,batch,repo):
    st.subheader('Received from Onboarding',help='Versioned item records passed by Onboarding; no duplicate initial upload is required.')
    if not batch:return
    queue=store.catalog_queue(batch)
    st.caption(f'{len(queue):,} current versions awaiting Catalog assessment. Vendor approval may remain pending during content preparation.')
    if queue:
        with st.expander('Inspect incoming items and retry details'):
            st.dataframe(pd.DataFrame([{'SKU':r['entity'],'Version':r['version'],'State':r['handoff_state'],
                                      'Attempts':r['attempts'],'Last error':r['handoff_error']} for r in queue]),hide_index=True,width='stretch')
        if st.button('Validate received items / retry',type='primary',help='Run the installed Catalog rules and record a receipt for each current item version.'):
            try:
                with st.spinner('Validating received item versions…'):count=process_catalog_queue(store,batch,repo)
                st.success(f'Catalog acknowledged {count:,} item versions. Review their outcomes below.');st.rerun()
            except Exception as exc:st.error('Handoff retained for correction or retry: '+str(exc))
    with st.expander('Upload Catalog corrections / enrichment'):
        st.caption('Only existing SKUs can be enriched. Download the current template; preserve SKU, vendor, mandatory fields and workflow_revision. Return mandatory setup changes to Item Onboarding.')
        items=store.requests(batch,'item')
        template=[dict(row['payload'],workflow_revision=row['version']) for row in items]
        st.download_button('Download current enrichment template',pd.DataFrame(template).to_csv(index=False).encode(),
                           'catalog-enrichment-'+batch+'.csv','text/csv',on_click='ignore')
        uploaded=st.file_uploader('Catalog enrichment file',type=['csv','xlsx'],help='Current template containing only SKUs from this batch and their workflow revisions.')
        actor=st.text_input('Correction recorded by',help='The person submitting these enrichment changes.')
        if st.button('Save enrichment and revalidate'):
            try:
                if uploaded is None:raise ValueError('Choose a correction file.')
                frame=pd.read_csv(uploaded) if uploaded.name.lower().endswith('.csv') else pd.read_excel(uploaded)
                store.enrich(batch,records(frame),actor)
                with st.spinner('Revalidating corrected items…'):count=process_catalog_queue(store,batch,repo)
                st.success(f'{count:,} revised item versions evaluated.');st.rerun()
            except Exception as exc:st.error(str(exc))


def _frame(rows):
    return pd.DataFrame([{'Request':r['id'],'Type':r['kind'].title(),'Record':r['entity'],'Version':r['version'],
      'Status':r['Status'],'Assigned team':r['team'],'Owner':r['owner'] or 'Unassigned','Due':r['due'] or 'Not set',
      'Next team':r['Next team'],'Next action':r['Next action']} for r in rows])


def summary(store,batch,kind=None):
    if not batch:return
    rows=[r for r in store.board(batch) if not kind or r['kind']==kind]
    from .dashboard import evidence,source_status
    checks=evidence(store,batch)
    metrics=[('Current records',len(rows),'Current request versions in this stage.'),('Data checks clear',sum(source_status(r,checks)=='Clear' for r in rows),'Source rules pass; approval and execution are separate.'),('Approval eligible',sum(r['Approval eligible'] and not r['Approved'] for r in rows),'Ready for a human decision, not yet approved.'),('Execution eligible',sum(r['Execution eligible'] for r in rows),'All current execution requirements pass; execution is simulated.')]
    for col,(label,value,definition) in zip(st.columns(4),metrics):col.metric(label,value,help=definition)
    st.caption('Measures overlap: data clearance, approval eligibility and execution permission are different stages, not additive totals.')


def actions(store,batch,kind=None,key='actions',compact=False):
    if not batch:return
    rows=[r for r in store.board(batch) if not kind or r['kind']==kind]
    st.subheader('Top Recommended Actions',help='Current blockers and the receiving team, linked to a persistent request.')
    team=st.selectbox('Filter accountable / next team',['All teams']+list(TEAMS),key=key+'_filter',help='Include requests assigned to this team or requiring its next action.')
    filtered=[r for r in rows if team=='All teams' or team in (r['team'],r['Next team'])]
    pending=[r for r in filtered if r['Status']!='ERP acknowledged (simulated)']
    pending.sort(key=lambda r:(r['Status']!='Blocked',r['due'] or '9999',{'vendor':0,'item':1,'po':2}[r['kind']],r['entity']))
    # Group repeated defects, retaining distinct affected entities and PO lines.
    all_rows=store.board(batch)
    buying=[r for r in all_rows if r['kind']=='po']
    groups={}
    for row in pending:
        group=groups.setdefault((row['kind'],row['Next team'],row['Next action']),[])
        group.append(row)
    grouped=[]
    for (request_kind,next_team,next_action),members in groups.items():
        entities={r['entity'] for r in members}
        linked=[p for p in buying if (p['entity'] in entities if request_kind=='po' else
                str(p['payload'].get('sku',p['payload'].get('SKU',''))) in entities if request_kind=='item' else
                str(p['payload'].get('vendor_id',p['payload'].get('Vendor ID',''))) in entities)]
        skus={str(p['payload'].get('sku',p['payload'].get('SKU',''))) for p in linked}
        if request_kind=='item':skus.update(entities)
        if request_kind=='vendor':skus.update(r['entity'] for r in all_rows if r['kind']=='item' and str(r['payload'].get('vendor_id')) in entities)
        skus.discard('')
        owners={r['owner'] if r['team']==next_team and r['owner'] else 'Unassigned to this team' for r in members}
        owner=next(iter(owners)) if len(owners)==1 else 'Multiple owners'
        grouped.append({'Team / owner':next_team+' / '+owner,'SKUs':len(skus),
                        'PO lines':len(linked),'Due':min((r['due'] for r in members if r['due']),default='Not set'),
                        'Next action':('PO' if request_kind=='po' else request_kind.title())+': '+next_action})
    frame=pd.DataFrame(grouped if compact else grouped[:10])
    if compact:
        st.caption(f'{len(pending):,} pending requests · {len(grouped):,} action groups. Choose a team, inspect corrections, then assign the next step.')
        if not frame.empty:
            frame.insert(0,'No',range(1,len(frame)+1))
            from orchestration.presentation import detail_table
            detail_table(frame,title='Priority corrections',export_key='parent_priority_corrections',
                         context={'Batch':batch,'Team filter':team,'Scope':'All recommendation groups matching the team filter; SKU and PO counts overlap between groups.'},hide_index=True,width='stretch')
        else:st.success('No pending requests in this team filter.')
        frame=pd.DataFrame()
    if not frame.empty:
        frame.insert(0,'No',range(1,len(frame)+1))
        st.dataframe(frame,hide_index=True,width='stretch',column_config={
            'No':st.column_config.NumberColumn(width='small'),
            'Team / owner':st.column_config.TextColumn(width='medium',help='Receiving team and named owner; change ownership in the form below.'),
            'SKUs':st.column_config.NumberColumn(width='small'),
            'PO lines':st.column_config.NumberColumn(width='small'),
            'Due':st.column_config.TextColumn(width='small'),
            'Next action':st.column_config.TextColumn(width='medium',help='Full correction or dependency; inspect exact records in Evidence.')})
        st.caption('Top 10 groups by blocker, deadline and upstream stage. Counts are distinct within each row and are not additive. Evidence contains every request and full finding.')
    elif not compact:st.success('No pending requests in this team filter.')
    if not filtered:return
    from .clarity import download_register
    download_register(store,batch,key+'_register')
    with st.expander('Assign, reassign or return a request'):
        by_id={r['id']:r for r in filtered}
        identifier=st.selectbox('Request to update',list(by_id),format_func=lambda i:by_id[i]['kind'].title()+' · '+by_id[i]['entity'],key=key+'_request',help='Choose the exact request whose ownership or deadline will change.')
        selected=by_id[identifier]
        st.caption('Current assignment: '+selected['team']+' / '+(selected['owner'] or 'Unassigned')+'. Next required action: '+selected['Next team']+'. When changing teams, name an owner for that receiving team.')
        with st.form(key+'_assignment_'+identifier):
            receive=st.selectbox('Receiving team',TEAMS,index=TEAMS.index(selected['team']) if selected['team'] in TEAMS else 0,help='The team expected to perform the next action.')
            owner=st.text_input('Named owner',value=selected['owner'],help='The individual responsible for the request.')
            due=st.text_input('Due date',value=selected['due'],placeholder='YYYY-MM-DD',help='Deadline for the assigned correction or approval.')
            status=st.selectbox('Work status',['Open','In progress','Waiting approval','Returned','On hold'],help='Reported work progress; it cannot override validation or approve execution.')
            actor=st.text_input('Recorded by',help='Your name for the audit record.')
            reason=st.text_input('Handoff reason / next step',help='Why this is being reassigned and what the receiving team must do.')
            if st.form_submit_button('Save ownership change'):
                try:
                    if receive!=selected['team'] and owner.strip()==selected['owner'].strip() and owner.strip():
                        raise ValueError('When changing teams, enter the receiving team owner rather than retaining the previous owner automatically.')
                    store.assign(identifier,selected['etag'],receive,owner,due,status,actor,reason);st.rerun()
                except ValueError as exc:st.error(str(exc))


def review(store,batch,kind=None,key='review'):
    if not batch:return
    rows=[r for r in store.board(batch) if not kind or r['kind']==kind]
    st.subheader('Approvals & integration handoff',help='Approve current validated versions, then separately simulate the downstream acknowledgement.')
    st.caption('Local prototype: reviewer names are recorded, not authenticated. Finance owns vendor approval, Catalog Operations owns item approval, Buying Operations owns PO approval. No message or transaction is sent to an ERP.')
    with st.expander('Record human approvals'):
        eligible={r['id']:r for r in rows if r['Approval eligible'] and not r['Approved']}
        st.caption(f'{len(eligible):,} current versions eligible. Critical findings block approval. Noncritical warnings require explicit reviewer acknowledgement.')
        all_selected=st.checkbox('Select all currently eligible versions',key=key+'_all_approve',help='Include exactly the eligible versions shown in this batch; changed versions will be rejected on save.')
        selected=list(eligible) if all_selected else st.multiselect('Versions to approve',list(eligible),format_func=lambda i:eligible[i]['kind']+' · '+eligible[i]['entity'],key=key+'_approve_list',help='Choose current requests to approve together.')
        actor=st.text_input('Reviewer name',key=key+'_reviewer',help='The named reviewer responsible for this approval.')
        reason=st.text_input('Approval reason',key=key+'_reason',help='Why these current records can proceed to the next gate.')
        warning_selected=[eligible[i] for i in selected if eligible[i]['Warning review']]
        if warning_selected:
            st.warning(f'{len(warning_selected):,} selected versions have noncritical warnings. Inspect their findings in Audit & Data before deciding.')
        accept_warnings=st.checkbox('I reviewed and accept the selected noncritical warnings',key=key+'_accept_warnings',help='Records explicit acceptance; this cannot override a critical finding or a missing prerequisite.') if warning_selected else False
        if st.button('Approve selected versions',key=key+'_approve',disabled=not selected):
            try:store.approve([(i,eligible[i]['etag']) for i in selected],actor,reason,accept_warnings=accept_warnings);st.rerun()
            except ValueError as exc:st.error(str(exc))
    with st.expander('Simulate ERP acknowledgement'):
        eligible={r['id']:r for r in rows if r['Execution eligible'] and not r['ERP receipt']}
        st.caption('Sequence: approved vendor â†’ vendor master acknowledgement â†’ approved Catalog item â†’ item setup acknowledgement â†’ approved PO â†’ PO acknowledgement. This is a local simulation only.')
        all_selected=st.checkbox('Select all currently executable versions',key=key+'_all_sim',help='Only approved versions whose upstream prerequisites are satisfied can be included.')
        selected=list(eligible) if all_selected else st.multiselect('Versions to simulate',list(eligible),format_func=lambda i:eligible[i]['kind']+' · '+eligible[i]['entity'],key=key+'_sim_list',help='Choose approved records for a local simulated receipt.')
        actor=st.text_input('Simulation recorded by',key=key+'_sim_actor',help='The person recording this local integration test.')
        reason=st.text_input('Simulation reason',key=key+'_sim_reason',help='Why this downstream handoff is being tested.')
        if st.button('Create simulated acknowledgement',key=key+'_simulate',disabled=not selected):
            try:store.simulate_erp([(i,eligible[i]['etag']) for i in selected],actor,reason);st.rerun()
            except ValueError as exc:st.error(str(exc))


def evidence(store,batch,key='evidence'):
    if not batch:return
    from orchestration.presentation import detail_table
    detail_table(_frame(store.board(batch)),title='Current shared requests',export_key=key+'_requests',context={'Batch':batch},hide_index=True,width='stretch')
    detail_table(pd.DataFrame(store.findings(batch)),title='Current validation findings',export_key=key+'_findings',context={'Batch':batch},hide_index=True,width='stretch')
    history=pd.DataFrame(store.history(batch))
    if not history.empty:
        history['created_at']=pd.to_datetime(history['created_at'],utc=True).dt.tz_convert('Asia/Kolkata').dt.strftime('%d-%m-%y %H:%M:%S IST')
    detail_table(history,title='Shared request and handoff history',export_key=key+'_history',context={'Batch':batch,'Time zone':'India Standard Time'},hide_index=True,width='stretch')
    with st.expander('Download current source files'):
        st.caption('Use these current versions for standalone tests or corrections. Preserve identifiers and gender; Catalog enrichment uses its versioned template instead.')
        for kind in ('vendor','item','po'):
            source=[{k:v for k,v in r['payload'].items() if not k.startswith('_')} for r in store.requests(batch,kind)]
            if source:st.download_button('Download '+kind+' CSV',pd.DataFrame(source).to_csv(index=False).encode(),kind+'-'+batch+'.csv','text/csv',key=key+'_source_'+kind,on_click='ignore')


def workspace(selected_batch=None):
    if selected_batch is None:
        store,batch=batch_selector('parent')
    else:
        _definitions()
        store,batch=WorkflowStore(),selected_batch
    st.caption('Onboarding â†’ Catalog â†’ Buying. One batch, versioned records, accountable handoffs. Earlier saved launch assessments are available in History.')
    launch,action,evid,rev=st.tabs(['Dashboard','Actions','Evidence','Review & audit'])
    with launch:
        if batch:
            import importlib
            from . import dashboard
            importlib.reload(dashboard).render(store,batch,'retail')
            with st.expander('Shipment and inventory decisions',expanded=False):
                from launch_assurance.uploaded_ui import render as render_logistics
                render_logistics(store,batch)
    with action:actions(store,batch,key='parent_actions',compact=True)
    with evid:
        if batch:
            st.subheader('Evidence at a glance',help='A short summary of current vendor, item and buying evidence for this batch.')
            board=store.board(batch)
            overview=[]
            for kind,label in [('vendor','Vendor'),('item','Item & Catalog'),('po','Buying')]:
                rows=[r for r in board if r['kind']==kind]
                overview.append({'Stage':label,'Records':len(rows),'Blocked':sum(r['Status']=='Blocked' for r in rows),
                                 'Awaiting approval':sum(r['Status']=='Ready for approval' for r in rows),
                                 'Approved':sum(r['Approved'] for r in rows)})
            st.dataframe(pd.DataFrame(overview),hide_index=True,width='stretch')
            st.caption('Current requests by stage. Approved records may still await downstream setup; use Actions for the next step.')
            with st.expander('Agent explanations',expanded=False):
                vendor_tab,catalog_tab,po_tab=st.tabs(['Vendor eligibility','Item & Catalog readiness','Buying request checks'])
                for tab,description in [(vendor_tab,'Checks vendor master data, compliance and commercial terms. Finance approves the current vendor version.'),(catalog_tab,'Onboarding checks mandatory setup fields; Catalog checks content. Catalog Operations approves the current item version.'),(po_tab,'Checks buying rules and matches Vendor, Category and Gender. Missing upstream approvals or setup receipts block progression.')]:
                    with tab:st.write(description)
            with st.expander('Supporting evidence & downloads',expanded=False):
                evidence(store,batch,key='parent_evidence')
    with rev:review(store,batch,key='parent_review')


def _definitions():
    import streamlit.components.v1 as components
    definitions={
      'Onboarding Intelligence':'Registers vendors and mandatory item data before specialist Catalog assessment.',
      'CatalogIQ Pro':'Enriches and validates product content received from Onboarding.',
      'Dashboard':'Current outcomes and the operational steps that can proceed.',
      'Vendor Onboarding':'Vendor master data, compliance findings and Finance approval readiness.',
      'Item Onboarding':'Mandatory SKU setup fields and the handoff to Catalog.',
      'Actions & Approvals':'Assign corrections, record human decisions and simulate eligible downstream handoffs.',
      'Audit & Data':'Versioned sources, recorded decisions and downloadable evidence.',
      'Launch decision':'Current PO prerequisites and the subset eligible for simulated execution.',
      'Actions':'Grouped recommendations and accountable request ownership.',
      'Evidence':'The current records and specialist contributions behind the decision.',
      'Review & audit':'Named human approvals and traceable simulated integration receipts.',
      'Vendor eligibility':'Vendor checks and the separate Finance approval prerequisite.',
      'Item & Catalog readiness':'Mandatory setup and enriched content checks for the requested SKU.',
      'Buying request checks':'Buying rules and vendor, category and gender matching for each PO line.',
      'Upload vendor and item requests':'The single initial intake for connected vendor and SKU records.',
      'Start a workflow batch':'Creates a shared scope to select in all workbenches.',
      'Upload Catalog corrections / enrichment':'Updates content for existing items without creating a second intake.',
      'Record human approvals':'Approve only current versions whose review prerequisites are satisfied.',
      'Simulate ERP acknowledgement':'Records a local demonstration receipt; it sends no production ERP transaction.',
      'Assign, reassign or return a request':'Moves accountable ownership while preserving the request history.',
      'Shared requests, ownership and approvals':'Current buying dependencies, accountable owners and approval controls.',
      'Download current intake sources':'Exports current records including retained Catalog enrichment.',
      'Download current source files':'Downloads current vendor, item and PO data for correction or isolated testing.',
      'Inspect incoming items and retry details':'Shows pending item versions and failed handoff attempts.'}
    components.html('<script>const definitions='+json.dumps(definitions)+''';const doc=window.parent.document;
    function apply(){doc.querySelectorAll('h1,h2,h3,h4,[role="tab"],summary p').forEach(el=>{const text=definitions[el.textContent.trim()];if(text){el.title=text;el.setAttribute('aria-description',text);}});}
    apply();const observer=new MutationObserver(apply);observer.observe(doc.body,{childList:true,subtree:true});window.addEventListener('unload',()=>observer.disconnect());</script>''',height=0)
