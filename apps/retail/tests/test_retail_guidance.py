import copy
from datetime import datetime,timezone,timedelta
import pytest
from tests.test_decision_workflow import inputs
from orchestration.retail_guidance import dependency_findings,recommended_actions,POLICY
from orchestration.decision_workflow import build_operations,ranked_actions
from orchestration.cycle_history import ActionRegistry,action_key
from orchestration.standalone_bridge import reconcile_standalone

def ready():
    f,p,r,c=inputs();c['po_dependency_policy']=POLICY
    f['vendor']['finance_approval_status']='Approved'
    f['catalog']['category']='Apparel';f['catalog']['gender']='Women';f['catalog']['catalog_setup_status']='Active'
    f['po']['category']='Apparel';f['po']['gender']='Women'
    return f,p,r,c

def test_missing_prerequisites_hold_po():
    f,p,r,c=ready();f['vendor']['finance_approval_status']='Pending'
    ops=build_operations(f,p,r,c)
    assert ops['counts']=={'Blocked':3}
    assert {a['Owner'] for a in ops['actions']}=={'Finance'}

def test_explicit_gender_not_inferred_from_division():
    f,p,r,c=ready();f['po']['gender']='';f['po']['division']='Womenswear'
    assert all(x['Status']=='Blocked' for x in build_operations(f,p,r,c)['lines'])

def test_item_setup_required_even_when_catalog_source_clear():
    f,p,r,c=ready();f['catalog']['catalog_setup_status']='Draft'
    assert build_operations(f,p,r,c)['counts']=={'Blocked':3}

def test_vendor_category_gender_and_source_rules_all_apply():
    f,p,r,c=ready();assert build_operations(f,p,r,c)['counts']=={'Clear candidate':3}
    f['po'].loc[0,'category']='Footwear'
    assert build_operations(f,p,r,c)['lines'][0]['Status']=='Blocked'
    f,p,r,c=ready();p['vendor']['vendor_health'][0].update(severity='CRITICAL',issues=['tax_id missing'])
    assert build_operations(f,p,r,c)['counts']['Blocked']==2

def test_handoff_preserves_history_and_group_counts(tmp_path):
    f,p,r,c=ready();f['vendor']['finance_approval_status']='Pending';ops=build_operations(f,p,r,c)
    reg=ActionRegistry(tmp_path,'CYCLE-'+'A'*16);reg.observe(ops['actions'],'run1')
    key=action_key(ops['actions'][0]);reg.assign(key,'Buyer','2099-01-01','Open','Reviewer','First assignment',assigned_team='Buying Operations')
    reg.assign(key,'Finance reviewer','2099-01-02','In progress','Reviewer','Return for approval',assigned_team='Finance')
    state=reg.load();assert state['events'][-1]['previous_owner']=='Buyer'
    assert state['events'][-1]['assigned_team']=='Finance'
    reg.observe(ops['actions'],'run2');assert reg.load()['actions'][key]['assigned_team']=='Finance'
    rows=recommended_actions(ranked_actions(reg.load(),ops),ops)
    assert sum(row['Corrections'] for row in rows)==3
    assert max(row['SKUs impacted'] for row in rows)<=2

def packages():
    result={}
    for kind,fields,health in [('vendor',['vendor_intelligence','vendor_onboarding'],'vendor_health'),('catalog',['catalog','item_onboarding','revenue_impact'],'sku_health'),('po',['po_intelligence','financial_impact'],'po_health')]:
        result[kind]=dict(schema=f'retail-intelligence.{kind}.v1',schema_version='1',source=kind,orchestration_run_id=kind,dataset_run_ids=['run'],policy_version='v1',executive_decision={},provenance={},synchronization_status='VERIFIED',business_cycle_id='shared',generated_at=datetime.now(timezone.utc).isoformat())
        result[kind].update({f:{} for f in fields});result[kind][health]=[{'id':'one'}]
    return result

def test_standalone_matches_and_rejects_different_cycles():
    p=packages();assert len(reconcile_standalone(p,p))==3
    fresh=copy.deepcopy(p);p['po']['business_cycle_id']='other'
    with pytest.raises(ValueError,match='different business cycles'):reconcile_standalone(p,fresh)

def test_standalone_rejects_stale_or_changed_findings():
    p=packages();fresh=copy.deepcopy(p);p['catalog']['sku_health'][0]['id']='other'
    with pytest.raises(ValueError,match='do not match'):reconcile_standalone(p,fresh)
    p=packages();p['po']['generated_at']=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    with pytest.raises(ValueError,match='stale'):reconcile_standalone(p,p)

def test_draft_request_handoff_is_audited_and_cannot_approve(tmp_path):
    from orchestration.request_desk import RequestDesk
    desk=RequestDesk(tmp_path,'cycle')
    fields={'Vendor':'V1','Category':'Apparel','Gender':'Unisex','SKU':'NOT-YET-SET-UP','Team':'Catalog Operations','Owner':'Catalog owner','Due':'2099-01-01','Status':'Waiting for Catalog'}
    key=desk.save(None,fields,'Buyer','Set up item',0)
    fields.update(Team='Finance',Owner='Finance owner',Status='Waiting for Finance')
    desk.save(key,fields,'Buyer','Item preparation complete; approval pending',1)
    state=desk.load()
    assert state['events'][-1]['Previous']['Team']=='Catalog Operations'
    assert state['requests'][key]['Team']=='Finance'
    with pytest.raises(ValueError,match='changed'):desk.save(key,fields,'Buyer','Stale edit',1)
    fields['Status']='Approved'
    with pytest.raises(ValueError,match='Unsupported'):desk.save(key,fields,'Buyer','Attempt approval',2)


def test_team_partition_keeps_other_teams_beyond_global_top_ten():
    from orchestration.retail_guidance import recommendations_by_team
    rows=[{'No.':i+1,'Team':'Catalog Operations','Category':str(i)} for i in range(12)]
    rows.append({'No.':13,'Team':'Finance','Category':'Approval'})
    groups=recommendations_by_team(rows)
    assert len(groups['Catalog Operations'])==12
    assert groups['Finance'][0]['No.']==1
    assert groups['Buying Operations']==[]
    assert rows[-1]['No.']==13
