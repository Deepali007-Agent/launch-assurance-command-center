from ui.decision_charts import outcome_rows,issue_rows,exposure_rows,bar_chart


def test_chart_populations_do_not_duplicate_lines_or_mix_currency():
    rows=[
        {'status':'FAIL','error_types':['Cost','Cost','Currency'],'is_flagged':True,'division':'A','cost_val':100,'commercial_value_included':False},
        {'status':'WARN','error_types':['Cost'],'is_flagged':True,'division':'B','cost_val':60,'commercial_value_included':True},
        {'status':'PASS','error_types':[],'is_flagged':False,'division':'A','cost_val':40},
    ]
    outcomes=outcome_rows(rows)
    assert sum(r['Lines'] for r in outcomes)==3
    assert round(sum(r['% of lines'] for r in outcomes),6)==100
    assert issue_rows(rows)[0]['Affected lines']==2
    assert exposure_rows(rows)==[{'Division':'B','Flagged commitment (INR)':60.0,'% of flagged commitment':100.0}]
    spec=bar_chart(outcomes,'Outcome','Lines','% of lines').to_dict()
    assert spec['layer'][0]['encoding']['y']['type']=='quantitative'
    assert spec['layer'][0]['encoding']['x']['axis']['labelAngle']==0


def test_empty_and_no_exposure_cases():
    assert issue_rows([])==[]
    assert exposure_rows([])==[]
    assert all(row['Lines']==0 for row in outcome_rows([]))
