from pathlib import Path
import hashlib
import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import pytest
from orchestration.launch_scope import scoped_frames, scope_identity, PolicyStore
from orchestration.financial_scenarios import financial_scenarios
from orchestration.local_safety import create_backup, restore_copy, verify_backup
from orchestration.cycle_history import ActionRegistry, action_key, saved_cycles
from orchestration.runtime import OrchestrationLedger
from tests.test_runtime import complete_assessments


def frames():
    return {'vendor':pd.DataFrame({'vendor_id':['V1','V2']}),
        'catalog':pd.DataFrame({'sku':['S1','S2'],'vendor_id':['V1','V2']}),
        'po':pd.DataFrame({'sku':['S1','S1','S2'],'vendor_id':['V1','V1','V2'],'po_id':['P1','P2','P3'],'location':['A','B','A'],'cost':['10','10','20'],'quantity':['2','3','4'],'reg_retail':['15','15','30'],'currency':['INR','INR','USD']})}


def test_scoped_launch_does_not_drop_other_locations_or_include_other_vendors():
    scoped=scoped_frames(frames(),'s1','a')
    assert list(scoped['po'].po_id)==['P1']
    assert list(scoped['vendor'].vendor_id)==['V1']
    assert list(scoped_frames(frames(),'S1')['po'].po_id)==['P1','P2']
    assert len(frames()['po'])==3


@pytest.mark.parametrize('sku,location',[('UNKNOWN',''),('S1','UNKNOWN'),('S2','B')])
def test_unknown_or_empty_scope_rejected(sku,location):
    with pytest.raises(ValueError): scoped_frames(frames(),sku,location)


def test_location_filter_requires_evidence():
    data=frames();data['po']=data['po'].drop(columns='location')
    with pytest.raises(ValueError,match='location'):scoped_frames(data,'','A')


def test_launches_share_cycle_without_overwriting_history(tmp_path):
    cycle='CYCLE-0123456789ABCDEF'
    for name in ['Web','Store']:
        folder=tmp_path/name;folder.mkdir()
        result={'business_cycle_id':cycle,'review_scope_id':scope_identity(cycle,name),'run_id':name}
        (folder/'result.json').write_text(json.dumps(result))
    assert len(saved_cycles(tmp_path))==2
    assert scope_identity(cycle,'')==cycle


def test_policy_versions_immutable_and_independent(tmp_path):
    store=PolicyStore(tmp_path)
    first=store.save('Web','1','image_url,size','Internal content policy','Reviewer')
    with pytest.raises(ValueError,match='exists'):store.save('Web','1','material','Changed','Reviewer')
    second=store.save('Web','2','material','Updated policy','Reviewer')
    assert store.list()[first]['fields']==['image_url','size']
    assert store.list()[second]['fields']==['material']


def test_financial_scenarios_deduplicate_and_keep_currencies_separate():
    result=financial_scenarios(frames()['po'],{'S1'},{'V1'},{'P1'},50)
    inr,usd=result['rows']
    assert inr['Currency']=='INR'
    assert inr['Affected retail value']=='75.00'
    assert inr['Affected gross margin']=='25.00'
    assert inr['Scenario revenue exposure']=='37.50'
    assert inr['Scenario gross margin exposure']=='12.50'
    assert usd['Affected retail value']=='0'
    assert result['coverage_pct']==100


@pytest.mark.parametrize('invalid',['','NaN','Infinity','-1','1e100'])
def test_unmeasured_retail_is_not_zero_exposure(invalid):
    po=frames()['po'].iloc[:1].copy();po['reg_retail']=invalid
    result=financial_scenarios(po,{'S1'})
    assert result['coverage_pct']==0 and result['rows']==[]


def test_negative_gross_margin_retained():
    po=frames()['po'].iloc[:1].copy();po['reg_retail']='5'
    assert financial_scenarios(po,{'S1'})['rows'][0]['Affected gross margin']=='-10.00'


def test_verified_backup_roundtrip_and_no_live_overwrite(tmp_path):
    data=tmp_path/'data';data.mkdir()
    db=data/'ledger.db'
    with sqlite3.connect(db) as conn:
        conn.execute('create table events(value text)');conn.execute("insert into events values ('original')")
    (data/'evidence.json').write_text('{"run":"one"}')
    archive=create_backup(data,tmp_path/'backups')
    target=restore_copy(archive,tmp_path/'recovered')
    with sqlite3.connect(target/'ledger.db') as conn:assert conn.execute('select value from events').fetchone()[0]=='original'
    assert (target/'evidence.json').read_text()=='{"run":"one"}'
    with pytest.raises(ValueError):restore_copy(archive,data)
    assert verify_backup(archive)


def test_backup_tampering_rejected(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('evidence.json','changed');z.writestr('BACKUP-MANIFEST.json',json.dumps({'files':{'evidence.json':hashlib.sha256(b'original').hexdigest()}}))
    with pytest.raises(ValueError,match='checksum'):verify_backup(archive)


def test_two_reviewers_cannot_silently_replace_the_same_decision(tmp_path):
    ledger=OrchestrationLedger(str(tmp_path/'data/x.db'))
    run=ledger.synchronize(complete_assessments())
    def decide(actor):
        try:
            ledger.decide_human_gate(run['orchestration_run_id'],True,actor,'Test',expected_gate='PENDING')
            return 'saved'
        except ValueError:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(decide,['First','Second']))
    assert sorted(results)==['conflict','saved']


def test_stale_assignment_revision_rejected(tmp_path):
    registry=ActionRegistry(tmp_path/'data/cycle_actions','CYCLE-0123456789ABCDEF')
    action={'Source':'Catalog','Identifier':'S1','Severity':'CRITICAL','Evidence required':'Size'}
    registry.observe([action],'RUN1');revision=registry.load()['revision'];key=action_key(action)
    registry.assign(key,'First','2026-10-01','Open','Reviewer','Test',expected_revision=revision)
    with pytest.raises(ValueError,match='another session'):
        registry.assign(key,'Second','2026-10-01','Open','Reviewer','Test',expected_revision=revision)
    assert registry.load()['actions'][key]['assigned_owner']=='First'

def test_local_lock_serializes_independent_processes(tmp_path):
    import subprocess,sys
    path=tmp_path/'counter.txt';path.write_text('0')
    program='''from pathlib import Path
import sys,time
from orchestration.local_safety import local_lock
p=Path(sys.argv[1])
for i in range(10):
    with local_lock(p.with_suffix('.lock')):
        value=int(p.read_text());time.sleep(.002);p.write_text(str(value+1))
'''
    jobs=[subprocess.Popen([sys.executable,'-c',program,str(path)]) for _ in range(3)]
    for job in jobs: assert job.wait(timeout=20)==0
    assert path.read_text()=='30'

def test_different_launch_evidence_cannot_mix_in_release(tmp_path):
    values=complete_assessments();cycle='CYCLE-0123456789ABCDEF'
    for value in values.values():value.business_cycle_id=scope_identity(cycle,'Web')
    values['po_intelligence'].business_cycle_id=scope_identity(cycle,'Store')
    ledger=OrchestrationLedger(str(tmp_path/'mixed.db'))
    run=ledger.synchronize(values)
    assert run['status']=='CYCLE_MISMATCH'
    with pytest.raises(ValueError,match='fresh agent outputs'):
        ledger.decide_human_gate(run['orchestration_run_id'],True,'Reviewer','Test')


def test_revalidation_invalidates_an_old_assignment_even_when_defect_unchanged(tmp_path):
    registry=ActionRegistry(tmp_path/'data/cycle_actions','CYCLE-0123456789ABCDEF')
    action={'Source':'Catalog','Identifier':'S1','Severity':'CRITICAL','Evidence required':'Size'}
    registry.observe([action],'RUN1');old=registry.load()['revision']
    registry.observe([action],'RUN2')
    with pytest.raises(ValueError,match='another session'):
        registry.assign(action_key(action),'Owner','2026-10-01','Open','Reviewer','Test',expected_revision=old)
