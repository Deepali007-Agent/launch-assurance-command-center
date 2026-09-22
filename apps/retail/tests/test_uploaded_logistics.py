from copy import deepcopy
import json
import pytest
from launch_assurance.uploaded import prepare,comparisons,ledger,basis
from launch_assurance.uploaded_ui import tables,record_review
from retail_workflow.store import WorkflowStore

@pytest.fixture
def inputs():
 board=[{'kind':'po','Execution eligible':True,'payload':{'SKU':'A','currency':'INR','Cost':60,'Reg Retail':100,'Total Quantity':100,'Location':'TX'}}]
 stock=[dict(sku='A',location='TX',opening_stock=0,daily_demand=10,safety_stock=0,transfer_cost_per_unit=1,transfer_lead_days=1),dict(sku='A',location='DL',opening_stock=100,daily_demand=2,safety_stock=20,transfer_cost_per_unit=1,transfer_lead_days=1)]
 ships=[dict(shipment_id='S',sku='A',destination='TX',quantity=100,promised_day=0,milestone_delay_days=4,expedite_days_saved=3,expedite_cost=20)]
 return board,stock,ships

def test_alternatives_share_baseline(inputs):
 model=prepare(*inputs,7);options=comparisons(model)
 assert len(options)==3 and sum(r['Recommendation']=='Recommended' for r in options)==1
 exp=next(r for r in options if r['Option']=='Expedite')
 assert exp['Revenue impact (INR)']==3000 and exp['Net margin impact (INR)']==1180
 move=next(r for r in options if r['Option']=='Reallocate stock')['Transfer']
 assert ledger(model,'A',move=move)['ending']['DL']>=20

def test_blocked_sku_cannot_be_expedited(inputs):
 inputs[0][0]['Execution eligible']=False
 rows=comparisons(prepare(*inputs,7))
 assert all(not r['Feasible'] for r in rows if r['Option']!='Take no action')
 assert all((r['Revenue impact (INR)'] or 0)==0 for r in rows)

@pytest.mark.parametrize('field,value',[('opening_stock',-1),('daily_demand',float('nan')),('safety_stock',''),('transfer_lead_days',1.5),('transfer_cost_per_unit',float('inf'))])
def test_bad_inventory_rejected(inputs,field,value):
 inputs[1][0][field]=value
 with pytest.raises(ValueError):prepare(*inputs,7)

@pytest.mark.parametrize('field,value',[('quantity',101),('expedite_cost',-1),('milestone_delay_days',float('nan')),('destination','UNKNOWN'),('sku','UNKNOWN')])
def test_bad_shipments_rejected(inputs,field,value):
 inputs[2][0][field]=value
 with pytest.raises(ValueError):prepare(*inputs,7)

def test_duplicate_and_partial_inventory(inputs):
 with pytest.raises(ValueError):prepare(inputs[0],inputs[1]+[inputs[1][0]],inputs[2],7)
 other=deepcopy(inputs[0][0]);other['payload']['SKU']='B'
 with pytest.raises(ValueError):prepare(inputs[0]+[other],inputs[1],inputs[2],7)

def test_ambiguous_price_rejected(inputs):
 other=deepcopy(inputs[0][0]);other['payload']['Cost']=65
 with pytest.raises(ValueError):prepare(inputs[0]+[other],inputs[1],inputs[2],7)

def test_currency_and_duplicate_shipments(inputs):
 with pytest.raises(ValueError):prepare(inputs[0],inputs[1],inputs[2]*2,7)
 inputs[0][0]['payload']['currency']='USD'
 with pytest.raises(ValueError):prepare(*inputs,7)

def test_unprofitable_expediting_not_recommended(inputs):
 inputs[2][0]['expedite_cost']=100000
 rows=comparisons(prepare(*inputs,7))
 assert not any(r['Option']=='Expedite' and r['Recommendation']=='Recommended' for r in rows)

def test_no_transfer_surplus(inputs):
 inputs[1][1]['opening_stock']=20
 row=next(r for r in comparisons(prepare(*inputs,7)) if r['Option']=='Reallocate stock')
 assert not row['Feasible']

def test_review_requires_current_evidence_and_feasible_option(inputs,tmp_path,monkeypatch):
 store=WorkflowStore(tmp_path/'state.db');batch=store.create_batch('Test','Tester');tables(store)
 data={'stock':inputs[1],'shipments':inputs[2],'horizon':7,'launch_date':'2026-10-01'}
 with store.connect(True) as db:db.execute('INSERT INTO logistics_inputs VALUES(?,?)',(batch,json.dumps(data)))
 monkeypatch.setattr(store,'board',lambda b:inputs[0])
 fingerprint=basis(store.token(batch),data)
 record_review(store,batch,data,fingerprint,'A','Expedite','Accept','Reviewer','Time-critical','Logistics owner','2026-10-01')
 inputs[0][0]['Execution eligible']=False
 with pytest.raises(ValueError,match='unavailable'):record_review(store,batch,data,fingerprint,'A','Expedite','Override','Reviewer','Override','Owner','2026-10-01')
 with store.connect(True) as db:store._event(db,batch,'','Changed','Tester',{})
 with pytest.raises(ValueError,match='changed'):record_review(store,batch,data,fingerprint,'A','Take no action','Defer','Reviewer','Wait','Owner','2026-10-01')

