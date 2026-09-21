from copy import deepcopy
import pytest
from launch_assurance.scenario import make_scenario
from launch_assurance.engine import source_checks,recommend,revalidate,simulate,eligible

@pytest.fixture(scope='module')
def source():
    scenario=make_scenario()
    return scenario,source_checks(scenario)

def test_existing_engines_produce_cohesive_split(source):
    scenario,checks=source
    assert all(r['passed'] for r in checks['onboarding'].values())
    assert checks['catalog']['LA-DRESS-B']['passed'] is False
    assert checks['buying']['LA-DRESS-C']['margin_pct']==33.33
    plan=recommend(scenario,checks)
    assert plan['clear']==['LA-DRESS-A','LA-DRESS-D']
    assert {a['kind'] for a in plan['actions']}=={'content','margin','expedite','transfer','release'}
    assert plan['baseline']['lost_units']==510
    assert plan['planned']['lost_units']==385
    assert plan['planned']['action_cost']==3300

def test_real_revalidation_unblocks_content_and_margin_without_double_count(source):
    scenario,checks=source;plan=recommend(scenario,checks)
    after=revalidate(scenario,checks,plan,[a['id'] for a in plan['actions']])
    assert len(after['clear'])==4
    assert after['result']['lost_units']==35
    assert after['protected_revenue']==712500
    assert after['protected_margin']==397950
    assert after['result']['action_cost']==3300
    assert sum(r['sold']+r['lost'] for r in after['result']['rows'])==700
    assert len({(r['sku'],r['location'],r['day']) for r in after['result']['rows']})==56
    assert scenario['items'][1]['material']=='' and scenario['pos'][2]['Cost']==1000

def test_transfer_reserves_donor_demand_and_safety(source):
    scenario,checks=source;plan=recommend(scenario,checks)
    assert plan['transfers']==[{'sku':'LA-DRESS-D','from':'Delhi','to':'Mumbai','quantity':65}]
    donor=next(r for r in plan['planned']['locations'] if (r['sku'],r['location'])==('LA-DRESS-D','Delhi'))
    assert donor['lost']==0 and donor['ending_stock']==20
    assert all(r['ending_stock']>=0 for r in plan['planned']['rows'])

def test_zero_donor_surplus_never_reallocates(source):
    scenario,checks=source;changed=deepcopy(scenario)
    for r in changed['stock']:
        if r['location']=='Delhi':r['opening_stock']=r['daily_demand']*7+r['safety_stock']
    assert recommend(changed,checks)['transfers']==[]

def test_unprofitable_expedite_rejected(source):
    scenario,checks=source;changed=deepcopy(scenario)
    changed['shipments'][0]['expedite_cost']=100000
    assert recommend(changed,checks)['expedited']==[]

def test_on_time_shipment_does_not_trigger_expedite(source):
    scenario,checks=source;changed=deepcopy(scenario)
    changed['shipments'][0]['milestone_delay_days']=0
    assert 'SHIP-A' not in recommend(changed,checks)['expedited']

def test_no_review_cannot_simulate_release(source):
    scenario,checks=source;plan=recommend(scenario,checks)
    after=revalidate(scenario,checks,plan,[],checker=lambda _:checks)
    assert after['release_reviewed'] is False
    assert after['result']['revenue']==0

def test_review_alone_does_not_bypass_critical_content_or_margin(source):
    scenario,checks=source;plan=recommend(scenario,checks)
    after=revalidate(scenario,checks,plan,['RELEASE'],checker=lambda _:checks)
    assert after['clear']==plan['clear']
    assert after['protected_revenue']==0 and after['protected_margin']==0

def test_zero_demand_has_no_protected_sales(source):
    scenario,checks=source;changed=deepcopy(scenario)
    for r in changed['stock']:r['daily_demand']=0
    plan=recommend(changed,checks)
    assert plan['baseline']['lost_units']==0
    assert plan['planned']['revenue']==0
    assert not plan['expedited'] and not plan['transfers']

def test_transfer_cannot_create_inventory(source):
    scenario,checks=source
    with pytest.raises(ValueError,match='donor inventory'):
        simulate(scenario,eligible(checks),transfers=[{'sku':'LA-DRESS-A','from':'Delhi','to':'Mumbai','quantity':121}])
