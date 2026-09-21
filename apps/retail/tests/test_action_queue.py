from datetime import date
import pytest
from orchestration.action_queue import queue_rows, validate_dependencies

def row(deadline='',severity='CRITICAL',status='Open',dependencies=()):
    return {'evidence':{'Source':'Catalog','Identifier':'S1','Severity':severity,'Evidence required':'Correct size'},'status':status,'due_date':deadline,'assigned_owner':'','dependencies':list(dependencies)}

def test_deadline_boundaries_and_resolved_exclusion():
    state={'actions':{'a':row('2026-09-15'),'b':row('2026-09-16'),'c':row('2026-09-23'),'d':row('2026-09-24'),'e':row(),'f':row(status='Resolved by revalidation')}}
    rows=queue_rows(state,today=date(2026,9,16))
    assert [r['Timing'] for r in rows]==['Overdue','Due today','Next 7 days','Later','No date']

def test_launch_fallback_and_dependency_completion():
    state={'actions':{'a':row(dependencies=['b']),'b':row(status='Resolved by revalidation')}}
    result=queue_rows(state,'2026-09-18',date(2026,9,16))[0]
    assert result['Days remaining']==2 and result['Deadline basis']=='Launch target' and result['Waiting on']==0
    state['actions']['b']['status']='Open'
    assert queue_rows(state,'2026-09-18',date(2026,9,16))[0]['Waiting on']==1

def test_dependencies_reject_self_unknown_and_circular():
    actions={'a':row(),'b':row(dependencies=['a'])}
    for deps in [['a'],['unknown'],['b']]:
        with pytest.raises(ValueError): validate_dependencies(actions,'a',deps)
    assert validate_dependencies(actions,'b',['a','a'])==['a']

def test_critical_precedes_overdue_warning():
    state={'actions':{'a':row('2026-10-01'),'b':row('2026-09-01','WARNING')}}
    assert queue_rows(state,today=date(2026,9,16))[0]['Action ID']=='a'
