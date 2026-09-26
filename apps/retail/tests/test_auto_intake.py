import importlib.util
import json
from pathlib import Path
import sys
import pandas as pd
import pytest
from retail_workflow.store import WorkflowStore
from retail_workflow.auto_intake import schema,scan,read_submission
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'apps/onboarding/src'),str(ROOT/'apps/catalog'),str(ROOT/'apps/po')]
spec=importlib.util.spec_from_file_location('submit_intake',ROOT/'scripts/submit_intake.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
from catalog_operations.persistence.repository import CatalogRepository

@pytest.fixture
def env(tmp_path):
    source=tmp_path/'source';source.mkdir()
    for role in ('vendor','catalog','po'):
        pd.read_csv(ROOT/'demo/corrected'/f'{role}.csv').head(3).to_csv(source/f'{role}.csv',index=False)
    store=WorkflowStore(tmp_path/'workflow.db');schema(store)
    inbox=tmp_path/'inbox';inbox.mkdir()
    repo=CatalogRepository('sqlite:///'+str(tmp_path/'catalog.db').replace('\\','/'))
    return source,store,inbox,lambda batch:repo

def seal(env):return module.submit(env[0],env[2],'launch-1','Test launch','Synthetic operator')
def test_automatic_checks_idempotent_and_gates(env):
    source,store,inbox,repo=env;seal(env)
    assert scan(store,inbox,repo)[0][1]=='Checked'
    batch=store.batches()[0]['id'];board=store.board(batch)
    assert len(board)==9
    assert not any(r['Approved'] or r['ERP receipt'] for r in board)
    assert not any(r['Execution eligible'] for r in board if r['kind']=='po')
    token=store.token(batch);scan(store,inbox,repo);assert store.token(batch)==token
    # Identical content under a fresh submission remains idempotent in the source ledger.
    seal(env);scan(store,inbox,repo);assert len(store.batches())==1 and store.token(batch)==token

def test_missing_hash_and_traversal_rejected_before_writes(env):
    source,store,inbox,repo=env;folder=seal(env)
    (folder/'vendor.csv').write_text('changed')
    assert 'checksum' in scan(store,inbox,repo)[0][1]
    assert not store.batches()
    m=json.loads((folder/'manifest.json').read_text());m['files']['vendor']['name']='../../secret.csv'
    (folder/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='inside'):read_submission(folder)

def test_retry_and_correction(env):
    source,store,inbox,repo=env;seal(env)
    def fail(batch):raise RuntimeError('Temporary catalog failure')
    assert 'Temporary' in scan(store,inbox,fail)[0][1]
    batch=store.batches()[0]['id'];assert len(store.requests(batch))==6
    scan(store,inbox,repo);assert len(store.requests(batch))==9
    frame=pd.read_csv(source/'vendor.csv',keep_default_na=False);frame.loc[0,'tax_id']='';frame.to_csv(source/'vendor.csv',index=False)
    seal(env);scan(store,inbox,repo)
    vendor=store.requests(batch,'vendor')[0];assert vendor['version']==2
    assert any(r['Status']=='Blocked' for r in store.board(batch))

def test_changed_submission_identity_and_duplicate_records(env):
    source,store,inbox,repo=env;folder=seal(env);scan(store,inbox,repo)
    m=json.loads((folder/'manifest.json').read_text());m['launch_name']='Changed'
    (folder/'manifest.json').write_text(json.dumps(m))
    assert 'already used' in scan(store,inbox,repo)[0][1]
    frame=pd.read_csv(source/'vendor.csv');pd.concat([frame,frame.head(1)]).to_csv(source/'vendor.csv',index=False)
    other=seal(env)
    with pytest.raises(ValueError,match='unique'):read_submission(other)

def test_named_owners_and_no_reassignment(env):
    source,store,inbox,repo=env
    module.submit(source,inbox,'launch-1','Test','Operator',{'Buying Operations':{'name':'Demo buyer','due':'2026-12-01'},'Catalog Operations':{'name':'Demo catalog owner','due':'2026-12-01'}})
    scan(store,inbox,repo);batch=store.batches()[0]['id']
    assert all(r['owner']=='Demo catalog owner' for r in store.requests(batch,'item'))
    assert all(r['owner']=='Demo buyer' for r in store.requests(batch,'po'))
    module.submit(source,inbox,'launch-1','Test','Operator',{'Buying Operations':{'name':'Replacement','due':'2026-12-01'}})
    scan(store,inbox,repo)
    assert all(r['owner']=='Demo catalog owner' for r in store.requests(batch,'item'))
    assert all(r['owner']=='Demo buyer' for r in store.requests(batch,'po'))


def test_out_of_order_and_stale_revision(env):
    source,store,inbox,repo=env
    first=seal(env);second=seal(env)
    # Filesystem folder names are random; processing must follow manifest revision.
    scan(store,inbox,repo)
    with store.connect() as db:assert db.execute('SELECT revision FROM auto_revisions').fetchone()[0]==2
    third=seal(env);m=json.loads((third/'manifest.json').read_text());m['revision']=1
    (third/'manifest.json').write_text(json.dumps(m))
    assert any('Stale revision' in result for _,result in scan(store,inbox,repo))

def test_logistics_uses_same_batch_without_approval_bypass(env):
    source,store,inbox,repo=env
    inventory=pd.read_csv(ROOT/'demo/logistics/inventory.csv')
    skus=set(pd.read_csv(source/'catalog.csv')['sku'])
    inventory[inventory.sku.isin(skus)].to_csv(source/'inventory.csv',index=False)
    shipment=pd.read_csv(ROOT/'demo/logistics/shipments.csv')
    shipment[shipment.sku.isin(skus)].to_csv(source/'shipments.csv',index=False)
    (source/'launch.json').write_text('{"launch_date":"2026-12-01","horizon":7}')
    seal(env);scan(store,inbox,repo)
    batch=store.batches()[0]['id']
    from launch_assurance.uploaded_ui import load
    from launch_assurance.uploaded import prepare
    data=load(store,batch);assert data is not None
    model=prepare(store.board(batch),data['stock'],data['shipments'],data['horizon'])
    assert not any(model['allowed'].values())
