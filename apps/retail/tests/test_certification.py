import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pandas as pd
import pytest
from orchestration.reconciliation import reconcile, financial_basis
from orchestration.runtime import OrchestrationLedger
from orchestration.contracts import AgentAssessment
from orchestration.intake import PublicationStore
from tests.test_runtime import complete_assessments
from tests.test_intake import payload


def frames():
    return {'vendor': pd.DataFrame([{'vendor_id':'V1'}]),
            'catalog': pd.DataFrame([{'sku':'S1','vendor_id':'V1'}]),
            'po': pd.DataFrame([{'po_id':'P1','sku':'S1','vendor_id':'V1','cost':'10','quantity':'3','currency':'INR'}])}

@pytest.mark.parametrize('kind', ['vendor','catalog','po'])
def test_missing_dataset(kind):
    data=frames();del data[kind]
    with pytest.raises(ValueError,match='Missing datasets'): reconcile(data)

@pytest.mark.parametrize('kind,field',[('vendor','vendor_id'),('catalog','sku'),('po','po_id')])
def test_missing_identifier_column(kind,field):
    data=frames();data[kind]=data[kind].drop(columns=[field])
    with pytest.raises(ValueError,match='mandatory'): reconcile(data)

@pytest.mark.parametrize('kind',['vendor','catalog','po'])
def test_duplicate_identity(kind):
    data=frames();data[kind]=pd.concat([data[kind],data[kind]])
    with pytest.raises(ValueError,match='duplicate identity'): reconcile(data)

@pytest.mark.parametrize('field,value',[('sku','UNKNOWN'),('vendor_id','UNKNOWN')])
def test_broken_link(field,value):
    data=frames();data['po'].loc[0,field]=value
    assert reconcile(data)[1]

@pytest.mark.parametrize('value',['','0','-1','NaN','Infinity','not a number','1e40'])
def test_unmeasurable_values_never_zero_risk(value):
    po=frames()['po'];po.loc[0,'cost']=value
    result=financial_basis(po)
    assert result['coverage_pct']==0
    assert result['commitment_by_currency']=={}
    assert result['limitations']


def test_currency_and_overlapping_impacts_are_not_added_twice():
    po=pd.concat([frames()['po'], frames()['po']],ignore_index=True)
    po.loc[1,'currency']='USD'
    result=financial_basis(po,{'S1'},{'V1'},{'P1'})
    assert result['commitment_by_currency']=={'INR':'30.00','USD':'30.00'}
    assert result['affected_commitment_by_currency']=={'INR':'30.00','USD':'30.00'}
    assert result['coverage_pct']==100


def test_missing_currency_is_explicit():
    result=financial_basis(frames()['po'].drop(columns='currency'))
    assert result['coverage_pct']==0


def test_changed_evidence_cannot_inherit_approval(tmp_path):
    ledger=OrchestrationLedger(str(tmp_path/'x.db'));values=complete_assessments()
    run=ledger.synchronize(values)
    ledger.decide_human_gate(run['orchestration_run_id'],True,'Reviewer','Verified')
    values['po_intelligence']=replace(values['po_intelligence'],release_blockers=['Coverage missing'])
    changed=ledger.synchronize(values)
    assert changed['orchestration_run_id'] != run['orchestration_run_id']
    with pytest.raises(ValueError,match='cannot be approved'):
        ledger.decide_human_gate(changed['orchestration_run_id'],True,'Reviewer','Retry')


def test_future_evidence_not_fresh(tmp_path):
    values=complete_assessments()
    values['po_intelligence'].generated_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    assert OrchestrationLedger(str(tmp_path/'x.db')).synchronize(values)['status']=='STALE'


def test_mismatched_cycle(tmp_path):
    values=complete_assessments();values['po_intelligence'].business_cycle_id='OTHER'
    assert OrchestrationLedger(str(tmp_path/'x.db')).synchronize(values)['status']=='CYCLE_MISMATCH'


def test_conflicting_retry_rejected(tmp_path):
    store=PublicationStore(str(tmp_path/'x.db'));data=payload();store.receive('PUB-X',data)
    data['catalog']['health_score']=99
    with pytest.raises(ValueError,match='different evidence'):store.receive('PUB-X',data)


def test_decision_requires_reason(tmp_path):
    ledger=OrchestrationLedger(str(tmp_path/'x.db'));run=ledger.synchronize(complete_assessments())
    with pytest.raises(ValueError,match='reason'):ledger.decide_human_gate(run['orchestration_run_id'],True,'Reviewer','')

@pytest.mark.parametrize('change',[{'ready_records':11},{'financial_exposure':float('nan')},{'score':float('nan')}])
def test_invalid_assessment_numbers(change):
    with pytest.raises(ValueError):replace(complete_assessments()['catalog_iq'],**change)

def test_evidence_aging_after_review_is_rechecked_at_approval(tmp_path, monkeypatch):
    import orchestration.runtime as runtime
    ledger = OrchestrationLedger(str(tmp_path / 'aging.db'))
    run = ledger.synchronize(complete_assessments())
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    class LaterClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return later if tz else later.replace(tzinfo=None)
    monkeypatch.setattr(runtime, 'datetime', LaterClock)
    with pytest.raises(ValueError, match='fresh agent outputs'):
        ledger.decide_human_gate(run['orchestration_run_id'], True, 'Reviewer', 'Review aged overnight')
    assert ledger.get(run['orchestration_run_id'])['status'] == 'STALE'
    assert not any(event['event_type'] == 'HUMAN_APPROVED' for event in ledger.get(run['orchestration_run_id'])['events'])
