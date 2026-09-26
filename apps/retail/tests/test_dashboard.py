from retail_workflow.dashboard import readiness,po_state,history
from retail_workflow.store import WorkflowStore

def row(kind,key,payload=None,eligible=False,blockers=None):
    return {'kind':kind,'id':key,'entity':key,'payload':payload or {},'Execution eligible':eligible,'Blockers':blockers or []}

def test_readiness_checks_linked_content_before_approval_bucket():
    vendor=row('vendor','v');item=row('item','s');po=row('po','p',{'SKU':'s','Vendor ID':'v'},blockers=[{'reason':'Current vendor version requires Finance approval'}])
    assert readiness([vendor,item,po],{('s','Catalog'):{'status':'Blocked'}})=={'Correction required':1}
    assert readiness([vendor,item,po],{('s','Catalog'):{'status':'Clear'}})=={'Awaiting prerequisites':1}

def test_readiness_is_mutually_exclusive_and_never_assumes_approval():
    rows=[row('po','a',eligible=True),row('po','b',blockers=[{'reason':'PO correction required: invalid cost'}]),row('po','c',blockers=[{'reason':'Current version needs human approval'}])]
    result=readiness(rows,{})
    assert result=={'Eligible':1,'Correction required':1,'Awaiting prerequisites':1}
    assert sum(result.values())==len(rows)

def test_no_history_is_not_synthetic_trend(tmp_path):
    store=WorkflowStore(tmp_path/'db.sqlite');batch=store.create_batch('Empty','Test')
    assert history(store,batch).empty
