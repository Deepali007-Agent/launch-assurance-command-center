from pathlib import Path
import hashlib
import json
import pytest
from orchestration.cycle_history import saved_cycles, saved_inputs, ActionRegistry, action_key

CYCLE='CYCLE-0123456789ABCDEF'

def action(issue='Missing tax ID'):
    return {'Source':'Vendor','Identifier':'V1','Severity':'CRITICAL','Evidence required':issue}


def test_assignment_survives_new_registry_and_is_audited(tmp_path):
    registry=ActionRegistry(tmp_path,CYCLE)
    registry.observe([action()],'RUN1')
    key=action_key(action())
    registry.assign(key,'Jamie Patel','2026-10-01','In progress','Alex Chen','Vendor confirmed correction deadline')
    state=ActionRegistry(tmp_path,CYCLE).load()
    assert state['actions'][key]['assigned_owner']=='Jamie Patel'
    assert state['actions'][key]['due_date']=='2026-10-01'
    assert state['events'][-1]['actor']=='Alex Chen'
    assert state['events'][-1]['run_id']=='RUN1'


@pytest.mark.parametrize('owner,deadline,status,actor,reason',[
    ('','2026-10-01','Open','Reviewer','Assign'),
    ('Owner','invalid','Open','Reviewer','Assign'),
    ('Owner','2026-10-01','Resolved by revalidation','Reviewer','Assign'),
    ('Owner','2026-10-01','Open','','Assign'),
    ('Owner','2026-10-01','Open','Reviewer',''),
])
def test_incomplete_assignment_or_manual_resolution_rejected(tmp_path,owner,deadline,status,actor,reason):
    registry=ActionRegistry(tmp_path,CYCLE);registry.observe([action()],'RUN1')
    with pytest.raises(ValueError):registry.assign(action_key(action()),owner,deadline,status,actor,reason)
    assert registry.load()['actions'][action_key(action())]['status']=='Open'


def test_only_revalidation_resolves_actions_and_new_defect_is_open(tmp_path):
    registry=ActionRegistry(tmp_path,CYCLE);registry.observe([action()],'RUN1')
    registry.assign(action_key(action()),'Jamie','2026-10-01','Ready to revalidate','Alex','Corrected source received')
    registry.observe([action()],'RUN2')
    assert registry.load()['actions'][action_key(action())]['status']=='Ready to revalidate'
    registry.observe([action('Missing bank verification')],'RUN3')
    state=registry.load()
    assert state['actions'][action_key(action())]['status']=='Resolved by revalidation'
    assert state['actions'][action_key(action())]['resolved_run_id']=='RUN3'
    assert state['actions'][action_key(action('Missing bank verification'))]['status']=='Open'
    registry.observe([action()], 'RUN4')
    reopened = registry.load()['actions'][action_key(action())]
    assert reopened['status'] == 'Open'
    assert 'resolved_run_id' not in reopened
    assert reopened['assigned_owner'] == 'Jamie'
    assert registry.load()['events'][-1]['event'] == 'REOPENED_BY_REVALIDATION'


def test_reopening_saved_cycle_checks_input_hashes(tmp_path):
    folder=tmp_path/'RUN1';folder.mkdir()
    result={'business_cycle_id':CYCLE,'run_id':'RUN1','cycle_name':'Autumn','folder':str(folder),'files':{},'hashes':{}}
    for kind in ('vendor','catalog','po'):
        data=b'column\nvalue\n';(folder/f'{kind}.csv').write_bytes(data)
        result['files'][kind]=f'{kind}.csv';result['hashes'][kind]=hashlib.sha256(data).hexdigest()
    (folder/'result.json').write_text(json.dumps(result),encoding='utf-8')
    reopened=saved_cycles(tmp_path)[CYCLE]
    assert reopened['run_id']=='RUN1'
    assert saved_inputs(reopened,tmp_path)['catalog'].getvalue()==b'column\nvalue\n'
    (folder/'catalog.csv').write_text('tampered',encoding='utf-8')
    with pytest.raises(ValueError,match='changed'):saved_inputs(reopened,tmp_path)


def test_saved_cycle_cannot_read_outside_workspace(tmp_path):
    with pytest.raises(ValueError,match='belong'):
        saved_inputs({'folder':str(tmp_path.parent)},tmp_path)
