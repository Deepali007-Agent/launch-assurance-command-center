import copy
from datetime import date
import pandas as pd
import pytest
from orchestration.decision_workflow import (build_operations,commercial,compare_runs,
    decision_state,enrich_report,ranked_actions)
from orchestration.cycle_history import ActionRegistry,action_key
from tests.test_local_pilot_completion import frames


def inputs():
    f=frames()
    payload={'vendor':{'vendor_health':[{'vendor_id':'V1','severity':'NONE'},{'vendor_id':'V2','severity':'NONE'}]},
             'catalog':{'sku_health':[{'sku':'S1','severity':'NONE'},{'sku':'S2','severity':'NONE'}]},
             'po':{'po_health':[{'po_id':'P1','sku':'S1','location':'A','severity':'NONE'},
                              {'po_id':'P2','sku':'S1','location':'B','severity':'NONE'},
                              {'po_id':'P3','sku':'S2','location':'A','severity':'NONE'}]}}
    report={'actions':[],'reconciliation_issues':[]}
    context={'launch_name':'Autumn','launch_date':'2099-10-01','channels':'Web'}
    return f,payload,report,context


def test_clean_subsets_are_candidates_not_approval():
    ops=build_operations(*inputs())
    assert ops['counts']=={'Clear candidate':3}
    assert ops['commitment']=={'INR':'50.00','USD':'80.00'}
    assert ops['critical_findings']==0
    label,_=decision_state({'status':'AWAITING_HUMAN_APPROVAL','decision_detail':{'status':'READY'}},ops)
    assert label=='Ready for human review'


def test_vendor_catalog_overlap_counts_commitment_once():
    f,p,r,c=inputs()
    p['vendor']['vendor_health'][0].update(severity='CRITICAL',issues=['Bank approval missing'])
    p['catalog']['sku_health'][0].update(severity='CRITICAL',affected_fields=['image_url'])
    ops=build_operations(f,p,r,c)
    assert ops['counts']=={'Blocked':2,'Clear candidate':1}
    assert ops['blocked_commitment']=={'INR':'50.00'}
    assert len(ops['actions'])==2
    assert all(a['Affected lines']==2 for a in ops['actions'])


def test_missing_currency_is_an_assignable_row_correction():
    f,p,r,c=inputs(); f['po'].loc[0,'currency']=''
    ops=build_operations(f,p,r,c)
    assert ops['counts']=={'Blocked':1,'Clear candidate':2}
    a=ops['actions'][0]
    assert a['Missing fields']=='currency' and a['Affected lines']==1
    assert a['Identifier']=='P1 / S1 / A' and a['Unmeasured lines']==1
    assert ops['unmeasured_lines']==1 and ops['commitment']=={'INR':'30.00','USD':'80.00'}


@pytest.mark.parametrize('field,value',[('cost','NaN'),('quantity','0'),('currency',''),('cost','1e99')])
def test_unknown_values_never_become_zero_impact(field,value):
    row={'cost':'10','quantity':'2','currency':'INR',field:value}
    bad,_,amount=commercial(row)
    assert bad and amount is None


def test_missing_launch_metadata_blocks_all_candidates():
    f,p,r,c=inputs();ops=build_operations(f,p,r,{})
    assert len(ops['global_reasons'])==3 and ops['counts']=={'Clear candidate':3}
    assert decision_state({'status':'AWAITING_HUMAN_APPROVAL','decision_detail':{'status':'READY'}},ops)[0]=='Hold'


def test_po_sku_location_findings_do_not_collapse():
    f,p,r,c=inputs();f['po'].loc[1,'po_id']='P1'
    p['po']['po_health'][0].update(severity='CRITICAL',issues=['Date invalid'])
    p['po']['po_health'][1].update(po_id='P1',severity='CRITICAL',issues=['Date invalid'])
    ops=build_operations(f,p,r,c)
    assert len(ops['actions'])==2
    assert ops['actions'][0]['Affected lines']==1
    assert action_key(ops['actions'][0])!=action_key(ops['actions'][1])


def test_required_channel_fields_propagate_to_po():
    f,p,r,c=inputs();r['actions']=[{'Source':'Launch requirements','Identifier':'S2','Severity':'CRITICAL','Evidence required':'Supply size','Owner':'Catalog Operations'}]
    ops=build_operations(f,p,r,c)
    assert ops['blocked_commitment']=={'USD':'80.00'}
    assert ops['actions'][0]['Line IDs']==['P3 / S2 / A']


def test_resolution_and_reopening_are_distinct():
    f,p,r,c=inputs();clean=enrich_report(f,p,r,c)
    f['po'].loc[0,'currency']='';broken=enrich_report(f,p,r,c)
    assert len(compare_runs(clean,broken)['resolved'])==1
    reopened=compare_runs(broken,clean,[broken])
    assert len(reopened['reopened'])==1 and not reopened['new']
    assert len(compare_runs(broken,broken)['remaining'])==1


def test_escalation_persists_and_revalidation_preserves_owner(tmp_path):
    f,p,r,c=inputs();f['po'].loc[0,'currency']='';ops=build_operations(f,p,r,c)
    registry=ActionRegistry(tmp_path,'CYCLE-0123456789ABCDEF');registry.observe(ops['actions'],'run1')
    key=action_key(ops['actions'][0])
    registry.assign(key,'Buyer','2026-09-16','In progress','Reviewer','Fix currency',escalation_owner='Buying lead',escalation_note='Escalate tomorrow')
    registry.observe(ops['actions'],'run2')
    rows=ranked_actions(registry.load(),ops,today=date(2026,9,17))
    assert rows[0]['Owner']=='Buyer' and rows[0]['Escalation owner']=='Buying lead'
    assert rows[0]['Escalation']=='Escalate overdue correction'
    assert rows[0]['Affected commitment']=='Unknown'


def test_stale_and_legacy_evidence_never_reads_ready():
    ops=build_operations(*inputs())
    assert decision_state({'status':'STALE'},ops)[0]=='Revalidation required'
    assert decision_state({},ops,legacy=True)[0]=='Revalidation required'


def test_incomplete_evidence_does_not_hide_warning_subset():
    f,p,r,c=inputs();p['po']['po_health'][1].update(severity='WARNING',issues=['Review date'])
    f['po'].loc[0,'currency']=''
    ops=build_operations(f,p,r,c)
    assert ops['counts']=={'Blocked':1,'Needs review':1,'Clear candidate':1}
    assert ops['review_commitment']=={'INR':'30.00'}


def test_bulk_assignment_is_atomic_and_stale_edits_rejected(tmp_path):
    f,p,r,c=inputs();f['po']['currency']='';ops=build_operations(f,p,r,c)
    registry=ActionRegistry(tmp_path,'CYCLE-0123456789ABCDEF');registry.observe(ops['actions'],'r1')
    before=registry.load();keys=list(before['actions'])
    with pytest.raises(ValueError): registry.assign_group(keys+['missing'],'Buyer','2026-10-01','Reviewer','Test')
    assert registry.load()==before
    registry.assign_group(keys,'Buyer','2026-10-01','Reviewer','Test','Lead',expected_revision=before['revision'])
    assert all(a['assigned_owner']=='Buyer' for a in registry.load()['actions'].values())
    with pytest.raises(ValueError,match='changed'): registry.assign_group(keys,'Other','2026-10-01','Reviewer','Test',expected_revision=before['revision'])


def test_history_ignores_unrelated_and_incomplete_records(tmp_path):
    import json
    from orchestration.decision_workflow import history_reports
    for name,value in [('incomplete',{}),('unrelated',{'business_cycle_id':'other','run_id':'other'})]:
        path=tmp_path/name;path.mkdir();(path/'result.json').write_text(json.dumps(value))
    assert history_reports({'business_cycle_id':'mine','run_id':'now'},tmp_path)==[]


def test_financial_scenario_uses_exact_line_scope():
    from orchestration.financial_scenarios import financial_scenarios
    f,p,r,c=inputs();f['po'].loc[1,'po_id']='P1'
    result=financial_scenarios(f['po'],affected_line_ids={'P1 / S1 / A'})
    assert result['rows'][0]['Affected retail value']=='30.00'
