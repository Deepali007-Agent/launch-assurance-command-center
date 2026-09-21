import pandas as pd
import pytest
from orchestration.launch_controls import context, evaluate, fingerprint, prioritized

def run(value, **columns):
    return evaluate(value, {'catalog':pd.DataFrame({'sku':['S1'],**columns})}, {'financial':{'coverage_pct':100},'reconciliation_issues':[]})

def test_all_twelve_problems_have_honest_coverage():
    result=run(context())
    assert len(result['coverage'])==12
    assert sum(r['Coverage']=='Not yet supported' for r in result['coverage'])==6
    assert not result['blockers']

def test_required_unavailable_control_holds():
    assert run(context(required_problems=[6]))['blockers']

def test_channel_attribute_missing_and_corrected():
    value=context(requirements='size')
    assert run(value)['blockers']
    assert run(value,size=[''])['actions'][0]['Identifier']=='S1'
    assert not run(value,size=['M'])['blockers']

def test_launch_scope_changes_evidence_identity():
    assert fingerprint(context(channels='Web'))!=fingerprint(context(channels='Store'))

def test_invalid_and_past_dates():
    with pytest.raises(ValueError): context('invalid')
    assert run(context('2000-01-01'))['blockers']

def test_blockers_precede_warnings():
    rows=[{'Severity':'WARNING'},{'Severity':'CRITICAL'}]
    assert prioritized(rows,'2026-10-01')[0]['Severity']=='CRITICAL'

def test_required_launch_control_cannot_pass_human_gate(tmp_path):
    from tests.test_runtime import complete_assessments
    from orchestration.runtime import OrchestrationLedger
    assessments=complete_assessments()
    assessments['po_intelligence'].release_blockers=run(context(required_problems=[6]))['blockers']
    ledger=OrchestrationLedger(str(tmp_path/'launch.db'))
    review=ledger.synchronize(assessments)
    with pytest.raises(ValueError,match='cannot be approved'):
        ledger.decide_human_gate(review['orchestration_run_id'],True,'Synthetic reviewer','Test')
