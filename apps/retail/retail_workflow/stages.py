"""Connected workbenches reusing the installed source-rule engines."""
from pathlib import Path
import pandas as pd
import streamlit as st
from . import ui


def onboarding(app):
    st.title('Onboarding Intelligence')
    st.caption('Start vendor and item requests once. Mandatory-complete items enter the Catalog queue; purchasing remains gated by Finance and item setup.')
    store,batch=ui.batch_selector('onboarding',allow_create=True)
    if not batch:return
    vendors=store.requests(batch,'vendor');items=store.requests(batch,'item')
    with st.expander('Upload vendor and item requests',expanded=not items):
        st.caption('Upload both sources initially. Later uploads update matching IDs and retain other requests. Download current sources before corrections to preserve Catalog enrichment. All monetary values use INR; no conversion is performed.')
        left,right=st.columns(2)
        with left:vendor_file=st.file_uploader('Vendor dataset',type=['csv','xlsx'],help='One record per vendor_id, with legal_name, country, contact_email and required compliance details.')
        with right:item_file=st.file_uploader('Item dataset',type=['csv','xlsx'],help='One record per sku; vendor_id, product_name, brand, category and price are mandatory. Supply gender for later PO matching.')
        actor=st.text_input('Intake recorded by',help='Your name is stored against these request versions.')
        if st.button('Validate onboarding data and send eligible items',type='primary'):
            try:
                if not vendor_file and not item_file:raise ValueError('Choose a vendor or item file to validate.')
                vendor_frame=app._read(vendor_file) if vendor_file else pd.DataFrame([r['payload'] for r in vendors])
                item_frame=app._read(item_file) if item_file else pd.DataFrame([r['payload'] for r in items])
                if vendor_frame.empty or item_frame.empty:raise ValueError('Provide both vendor and item sources for the first intake.')
                # Pure structural preflight and source assessments precede the single ledger transaction.
                from agents import assess_vendor
                from service import VendorIQService
                service=VendorIQService(app.ROOT/'data'/'shared_projection.db')
                accepted,rejected,errors=service.validate_frame(vendor_frame)
                if errors:raise ValueError('; '.join(e['issue'] for e in errors))
                assessments=[]
                for row in accepted:
                    assessments.extend(dict(result,vendor_id=str(row['vendor_id']).strip()) for result in assess_vendor(row))
                result=ui.save_onboarding(store,batch,pd.DataFrame(accepted),pd.DataFrame(assessments),item_frame,actor)
                st.session_state.connected_notice=f"Validated and saved. {result['queued']:,} mandatory-complete item versions handed to Catalog; {result['blocked']:,} require intake correction."
                st.rerun()
            except (ValueError,TypeError,KeyError,OSError) as exc:st.error(str(exc))
    if st.session_state.get('connected_notice'):st.success(st.session_state.pop('connected_notice'))
    if not vendors and not items:return
    executive,vendor_tab,item_tab,action,audit=st.tabs(['Executive Summary','Vendor Onboarding','Item Onboarding','Actions & Approvals','Audit & Data'])
    with executive:
        ui.summary(store,batch)
        st.info('Catalog preparation can proceed for mandatory-complete items while Finance review is pending. PO approval and simulated creation stay blocked until current vendor and item prerequisites are satisfied.')
    with vendor_tab:
        ui.summary(store,batch,'vendor')
        _outcomes(store,batch,'vendor','Vendor request outcomes')
        _root_causes(store,batch,'vendor')
    with item_tab:
        st.caption('This stage owns SKU identity, vendor linkage and mandatory setup attributes. Catalog owns content enrichment. A received Catalog record is not an ERP-created item.')
        _outcomes(store,batch,'item','Item request outcomes')
        _root_causes(store,batch,'item')
        st.metric('Awaiting Catalog validation',len(store.catalog_queue(batch)),help='Current item versions handed off but not yet acknowledged by Catalog.')
        st.link_button('Open Catalog received-items queue',__import__("os").environ.get("CATALOG_APP_URL", 'http://localhost:8507'))
    with action:
        ui.actions(store,batch,key='onboarding_actions')
        ui.review(store,batch,'vendor',key='onboarding_review')
    with audit:
        st.caption('Request ID identifies a continuing business request. Version identifies its current data revision. Every correction, ownership change, approval and simulated receipt is retained.')
        ui.evidence(store,batch,key='onboarding_evidence')
        with st.expander('Download current intake sources'):
            for kind in ['vendor','item']:
                data=[{k:v for k,v in r['payload'].items() if not k.startswith('_')} for r in store.requests(batch,kind)]
                st.download_button('Download current '+kind+' source',pd.DataFrame(data).to_csv(index=False).encode(),kind+'-current.csv','text/csv',on_click='ignore')


def _outcomes(store,batch,kind,title):
    import altair as alt
    rows=[r for r in store.board(batch) if r['kind']==kind]
    if not rows:return
    frame=pd.DataFrame(rows).groupby('Status').size().reset_index(name='Requests')
    frame['Share']=frame.Requests/len(rows)*100
    frame['Label']=frame.apply(lambda r:f"{r.Requests:,} · {r.Share:.1f}%",axis=1)
    bars=alt.Chart(frame).mark_bar().encode(x=alt.X('Status:N',axis=alt.Axis(labelAngle=0),title=None),y=alt.Y('Requests:Q',title='Requests'),tooltip=['Status','Requests',alt.Tooltip('Share:Q',format='.1f',title='% of requests')])
    labels=bars.mark_text(dy=-10).encode(text='Label:N')
    st.altair_chart((bars+labels).properties(title=title,height=260),use_container_width=True)


def catalog(app):
    st.title('CatalogIQ Pro')
    st.caption('Receive item requests from Onboarding, enrich their content, and review current versions. Direct initial uploads belong in Onboarding.')
    store,batch=ui.batch_selector('catalog')
    if not batch:return
    # A batch has its own Catalog projection; different launches cannot replace each other.
    from catalog_operations.persistence.repository import CatalogRepository
    root=Path(app.__file__).resolve().parents[1]
    folder=root/'data'/'shared_batches';folder.mkdir(parents=True,exist_ok=True)
    repo=CatalogRepository('sqlite:///'+str(folder/(batch+'.db')).replace('\\','/'))
    mode=st.radio('Catalog workspace',['Received items & enrichment','Leadership Intelligence','Actions & Approvals','Audit & Data'],horizontal=True,help='Receive first, inspect content results, then approve current versions and track handoffs.')
    if mode=='Received items & enrichment':
        ui.catalog_intake(store,batch,repo)
        ui.summary(store,batch,'item')
    elif mode=='Leadership Intelligence':
        ui.summary(store,batch,'item')
        current={r['entity']:r['version'] for r in store.requests(batch,'item')}
        if store.catalog_queue(batch):st.warning('New or corrected item versions await validation. Charts below describe the last Catalog assessment; shared approval status above always uses current versions.')
        if repo.list_current_items():app._leadership_workspace(repo,connected=True)
        else:st.info('Validate received items first to build Catalog intelligence.')
    elif mode=='Actions & Approvals':
        ui.actions(store,batch,'item',key='catalog_actions')
        ui.review(store,batch,'item',key='catalog_review')
    else:
        st.caption('Catalog receipts confirm assessment of a specific item version. ERP acknowledgement is a separate, explicitly simulated action after human approval.')
        ui.evidence(store,batch,key='catalog_evidence')


def _root_causes(store,batch,kind):
    import altair as alt
    frame=pd.DataFrame(store.findings(batch,kind))
    if frame.empty:
        st.caption('No source attribute findings in the current assessments. Approval and integration prerequisites remain separate.')
        return
    frame=frame[frame.Finding.astype(str).str.strip().str.lower().isin(['','none','null','nan'])==False]
    if frame.empty:return
    frame['Requirement']=frame.Finding.str.split(':').str[0].str.replace('Complete ','',regex=False)
    grouped=frame.groupby('Requirement')['Record'].nunique().reset_index(name='Records').sort_values('Records',ascending=False).head(8)
    total=len(store.requests(batch,kind));grouped['Share']=grouped.Records/total*100
    grouped['Label']=grouped.apply(lambda r:f'{r.Records:,} ({r.Share:.1f}%)',axis=1)
    chart=alt.Chart(grouped).mark_bar(color='#f4b860').encode(x=alt.X('Requirement:N',sort='-y',axis=alt.Axis(labelAngle=0,labelLimit=130),title=None),y=alt.Y('Records:Q',title='Affected records'),tooltip=['Requirement','Records',alt.Tooltip('Share:Q',format='.1f',title='% of source records')])
    st.altair_chart((chart+chart.mark_text(dy=-10).encode(text='Label:N')).properties(title='Top source root causes',height=260),width='stretch')
    st.caption('Distinct affected records per requirement; percentages use all records of this source type. Requirements overlap and cannot be added.')
