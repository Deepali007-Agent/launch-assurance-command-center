import pytest
from retail_workflow.store import WorkflowStore, Conflict


@pytest.fixture
def setup(tmp_path):
    store=WorkflowStore(tmp_path/'workflow.db');batch=store.create_batch('Launch','QC')
    vendor={'vendor_id':'V1','legal_name':'Vendor','currency':'INR'}
    item={'sku':'S1','vendor_id':'V1','product_name':'Shirt','brand':'Brand','category':'Apparel','gender':'Men','price':100,'description':'Original content'}
    store.ingest_onboarding(batch,[vendor],[item],{'V1':{'status':'Clear','findings':[]}},'QC')
    store.complete_catalog(store.catalog_queue(batch),{'S1':{'status':'Clear','findings':[]}})
    po={'PO_ID':'P1','SKU':'S1','Vendor ID':'V1','Class':'Apparel','gender':'Men'}
    result={'status':'PASS','errors':[],'warnings':[]}
    store.ingest_pos(batch,[po],[result],'QC')
    return store,batch,vendor,item,po,result


def finish(store,batch,kind):
    row=next(r for r in store.board(batch) if r['kind']==kind)
    store.approve([(row['id'],row['etag'])],'Reviewer','Test')
    row=next(r for r in store.board(batch) if r['kind']==kind)
    store.simulate_erp([(row['id'],row['etag'])],'Operator','Test')


def test_content_can_prepare_but_po_needs_finance_and_setup(setup):
    s,b,*_=setup
    assert next(r for r in s.board(b) if r['kind']=='item')['Approval eligible']
    po=next(r for r in s.board(b) if r['kind']=='po')
    assert not po['Approval eligible']
    assert any(x['team']=='Finance' for x in po['Blockers'])
    finish(s,b,'vendor');finish(s,b,'item');finish(s,b,'po')
    assert all(r['ERP receipt'] for r in s.board(b))


def test_source_revision_invalidates_downstream_approvals(setup):
    s,b,v,i,*_=setup
    for kind in ('vendor','item','po'):finish(s,b,kind)
    s.ingest_onboarding(b,[dict(v,legal_name='Corrected')],[i],{'V1':{'status':'Clear','findings':[]}},'QC')
    assert all(not r['Approved'] and not r['ERP receipt'] for r in s.board(b))


@pytest.mark.parametrize('field,value',[('Vendor ID','OTHER'),('Class','Footwear'),('gender','Women'),('SKU','UNKNOWN')])
def test_buying_identity_mismatch_blocks(setup,field,value):
    s,b,v,i,p,result=setup
    for kind in ('vendor','item'):finish(s,b,kind)
    identifier=s.ingest_pos(b,[dict(p,**{field:value})],[result],'QC')[0]
    assert s.gates([identifier])[identifier]


def test_noncritical_warning_requires_explicit_acceptance(setup):
    s,b,v,i,*_=setup
    s.ingest_onboarding(b,[v],[i],{'V1':{'status':'Review','findings':['Review contact email']}},'QC')
    row=next(r for r in s.board(b) if r['kind']=='vendor')
    assert row['Approval eligible'] and row['Warning review']
    with pytest.raises(ValueError,match='acknowledge'):s.approve([(row['id'],row['etag'])],'Reviewer','Reviewed')
    s.approve([(row['id'],row['etag'])],'Reviewer','Reviewed',accept_warnings=True)
    assert next(r for r in s.board(b) if r['kind']=='vendor')['Approved']


def test_critical_cannot_be_waived(setup):
    s,b,v,i,*_=setup
    s.ingest_onboarding(b,[v],[i],{'V1':{'status':'Blocked','findings':['Missing tax ID']}},'QC')
    row=next(r for r in s.board(b) if r['kind']=='vendor')
    with pytest.raises(ValueError):s.approve([(row['id'],row['etag'])],'Reviewer','Override',accept_warnings=True)


def test_retry_and_reupload_are_idempotent(setup):
    s,b,v,i,*_=setup
    token=s.token(b)
    s.ingest_onboarding(b,[v],[i],{'V1':{'status':'Clear','findings':[]}},'QC')
    assert s.token(b)==token
    finish(s,b,'vendor');row=next(r for r in s.board(b) if r['kind']=='vendor');token=s.token(b)
    s.simulate_erp([(row['id'],row['etag'])],'QC','Retry');assert s.token(b)==token


def test_enrichment_is_versioned_and_replay_preserves_it(setup):
    s,b,v,i,*_=setup
    row=s.requests(b,'item')[0]
    correction=dict(i,workflow_revision=str(row['version']),description='Enriched')
    s.enrich(b,[correction],'QC')
    s.ingest_onboarding(b,[v],[i],{'V1':{'status':'Clear','findings':[]}},'QC')
    assert s.requests(b,'item')[0]['payload']['description']=='Enriched'
    with pytest.raises(Conflict):s.enrich(b,[correction],'QC')
    current=s.requests(b,'item')[0]
    with pytest.raises(ValueError,match='Onboarding'):s.enrich(b,[dict(current['payload'],workflow_revision=str(current['version']),gender='Women')],'QC')


def test_assignment_and_hold_keep_validation_authoritative(setup):
    s,b,*_=setup
    row=s.requests(b,'vendor')[0]
    s.assign(row['id'],row['etag'],'Finance','Owner','','On hold','QC','Investigate')
    with pytest.raises(Conflict):s.assign(row['id'],row['etag'],'Finance','Other','','Open','QC','Stale')
    assert s.gates([row['id']],True)[row['id']]


def test_bulk_approval_failure_is_atomic(setup):
    s,b,*_=setup
    rows=s.board(b);v=next(r for r in rows if r['kind']=='vendor');p=next(r for r in rows if r['kind']=='po')
    with pytest.raises(ValueError):s.approve([(v['id'],v['etag']),(p['id'],p['etag'])],'QC','Blocked batch')
    assert all(not r['Approved'] for r in s.board(b))
