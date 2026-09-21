"""Calendar-based queue projection. Work status never changes release evidence."""
from datetime import date

RESOLVED='Resolved by revalidation'

def queue_rows(state, launch_date='', today=None):
    today=today or date.today()
    rows=[]
    for key, value in state['actions'].items():
        if value['status']==RESOLVED: continue
        evidence=value['evidence']
        deadline=value.get('due_date') or launch_date
        remaining=(date.fromisoformat(deadline)-today).days if deadline else None
        timing='No date' if remaining is None else 'Overdue' if remaining<0 else 'Due today' if remaining==0 else 'Next 7 days' if remaining<=7 else 'Later'
        waiting=[dep for dep in value.get('dependencies',[]) if state['actions'].get(dep,{}).get('status')!=RESOLVED]
        rows.append({'Action ID':key,'Source':evidence['Source'],'Record':evidence['Identifier'],
            'Severity':evidence.get('Severity',''),'Correction':evidence.get('Evidence required',''),
            'Owner':value.get('assigned_owner') or 'Unassigned','Deadline':deadline or 'Not set',
            'Deadline basis':'Assigned' if value.get('due_date') else 'Launch target' if launch_date else 'None',
            'Timing':timing,'Days remaining':remaining,'Status':value['status'],
            'Waiting on':len(waiting)})
    return sorted(rows,key=lambda r:(0 if r['Severity'] in {'CRITICAL','BLOCKED'} else 1,
        r['Days remaining'] if r['Days remaining'] is not None else 100000,r['Source'],r['Record']))

def validate_dependencies(actions, action_id, dependencies):
    dependencies=list(dict.fromkeys(dependencies))
    if action_id in dependencies: raise ValueError('An action cannot depend on itself.')
    if any(key not in actions for key in dependencies): raise ValueError('Unknown prerequisite action.')
    graph={key:list(value.get('dependencies',[])) for key,value in actions.items()}
    graph[action_id]=dependencies
    def visit(key,path):
        if key in path: raise ValueError('Dependencies must not contain a circular chain.')
        for dep in graph.get(key,[]): visit(dep,path|{key})
    visit(action_id,set())
    return dependencies
