from tests.test_po_engine import valid_row
from domain.po_engine import validate_row, build_financial
from agents.executive_agent import analyze_executive_decision


def test_non_inr_values_are_not_relabeled_or_added_to_inr_totals():
    rows=[validate_row(valid_row(currency=currency),index) for index,currency in enumerate(['INR','USD',''])]
    assert rows[0]['status']=='PASS'
    assert all(row['status']=='FAIL' for row in rows[1:])
    assert all(not row['commercial_value_included'] for row in rows[1:])
    assert build_financial(rows)['total_rev']==600
    assert rows[1]['currency']=='USD'


def test_division_priority_follows_risk_not_input_order():
    divisions=[{'division':'Low first','risk':'LOW','error_rate':1,'margin_gaps':0},
               {'division':'High second','risk':'HIGH','error_rate':60,'margin_gaps':100}]
    fin={'po_pass_rate':100,'at_risk_rev':0,'margin_gap':0}
    result=analyze_executive_decision(fin,[],divisions,{'sla_rate':100},[],[])
    assert result['top_division']=='High second'
    assert 'INR' in result['executive_summary'] and '$' not in result['executive_summary']
