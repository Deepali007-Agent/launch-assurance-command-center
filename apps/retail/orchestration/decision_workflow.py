"""Selected-launch operational projection. Never authorizes release itself."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from datetime import date
from pathlib import Path
import json
import pandas as pd
from orchestration.reconciliation import normalize
from orchestration.cycle_history import action_key

VERSION = 'retail-decision-workflow-1'


def identity(value):
    return str(value or '').strip().upper()


def commercial(row):
    """Return exact missing fields and measured cost commitment, never assumed zero."""
    bad=[]
    currency=identity(row.get('currency'))
    if len(currency)!=3 or not currency.isascii() or not currency.isalpha(): bad.append('currency')
    values=[]
    qty='total_quantity' if 'total_quantity' in row else 'quantity'
    for field in ('cost',qty):
        try:
            value=Decimal(str(row.get(field,'')))
            if not value.is_finite() or value<=0: raise InvalidOperation
            values.append(value)
        except (InvalidOperation,ValueError): bad.append(field)
    if bad: return bad,currency,None
    try:
        amount=(values[0]*values[1]).quantize(Decimal('.01'))
        if amount>Decimal('1000000000000'): return ['cost × quantity exceeds review limit'],currency,None
    except InvalidOperation: return ['cost × quantity exceeds review limit'],currency,None
    return [],currency,str(amount)


def line_id(row):
    return ' / '.join(identity(row.get(k)) for k in ('po_id','sku','location'))


def money(lines):
    totals={}
    for line in lines:
        if line['Commitment'] is not None:
            c=line['Currency']; totals[c]=totals.get(c,Decimal(0))+Decimal(line['Commitment'])
    return {c:str(v) for c,v in sorted(totals.items())}


def build_operations(frames, payloads, report, context):
    """Tie every correction to affected PO lines, preserving disjoint row populations."""
    po=normalize(frames['po']).to_dict('records')
    lines=[]
    for i,row in enumerate(po):
        bad,currency,amount=commercial(row)
        lines.append({'Line':line_id(row),'Evaluated row':i+2,'PO':identity(row.get('po_id')),
            'SKU':identity(row.get('sku')),'Vendor':identity(row.get('vendor_id')),
            'Location':identity(row.get('location')),'Currency':currency or 'Missing',
            'Commitment':amount,'Missing fields':', '.join(bad),'Issues':[], 'Status':'Clear candidate'})
    actions=[]
    def add(source,identifier,severity,correction,team,indices,fields='',scope='Record',**extra):
        selected=[lines[i] for i in indices]
        action={'Source':source,'Identifier':identifier,'Severity':severity,'Owner':team,
            'Due':'Before release' if severity=='CRITICAL' else 'Before approval',
            'Evidence required':correction,'Status':'Open','Revalidation':'Required',
            'Missing fields':fields,'Scope':scope,'Affected lines':len(selected),
            'Line IDs':[r['Line'] for r in selected],'Commitment by currency':money(selected),
            'Unmeasured lines':sum(r['Commitment'] is None for r in selected),**extra}
        actions.append(action)
        for i in indices:
            lines[i]['Issues'].append(correction)
            if severity=='CRITICAL': lines[i]['Status']='Blocked'
            elif lines[i]['Status']!='Blocked': lines[i]['Status']='Needs review'
    specs=[('vendor','vendor_health','vendor_id','Vendor','Vendor Operations'),
           ('catalog','sku_health','sku','Catalog','Catalog Operations'),
           ('po','po_health','po_id','Po','Buying Operations')]
    for kind,health,idfield,label,team in specs:
        for row in payloads[kind].get(health,[]):
            if row.get('severity') not in {'CRITICAL','WARNING'}: continue
            ident=identity(row.get(idfield))
            indices=[i for i,r in enumerate(lines) if
                (kind=='vendor' and r['Vendor']==ident) or
                (kind=='catalog' and r['SKU']==ident) or
                (kind=='po' and r['PO']==ident and (not row.get('sku') or r['SKU']==identity(row['sku']))
                 and (not row.get('location') or r['Location']==identity(row['location'])))]
            issue=row.get('issues') or row.get('affected_fields') or ['Correct source record']
            issue=', '.join(map(str,issue)) if isinstance(issue,list) else str(issue)
            extra={'SKU':identity(row.get('sku')),'Location':identity(row.get('location'))} if kind=='po' else {}
            add(label,ident,row['severity'],issue,team,indices,**extra)
    # Channel attribute actions are separate from catalog engine findings.
    for a in report.get('actions',[]):
        if a['Source']!='Launch requirements': continue
        indices=[i for i,r in enumerate(lines) if r['SKU']==identity(a['Identifier'])]
        add(a['Source'],a['Identifier'],a['Severity'],a['Evidence required'],a['Owner'],indices)
    for i,line in enumerate(lines):
        if line['Missing fields']:
            add('Commercial evidence',line['Line'],'CRITICAL',
                'Supply valid '+line['Missing fields']+' on this PO line and revalidate.',
                'Buying Operations',[i],fields=line['Missing fields'])
    if context.get('po_dependency_policy')=='vendor-category-gender-1':
        from orchestration.retail_guidance import dependency_findings
        for a in dependency_findings(frames):
            indices=[i for i,r in enumerate(lines) if r['Line']==a['Identifier']]
            add(a['Source'],a['Identifier'],a['Severity'],a['Evidence required'],a['Owner'],indices,
                fields=a['Missing fields'],SKU=a['SKU'],Location=a['Location'])
    global_reasons=[]
    for field,label in [('launch_name','launch name'),('launch_date','launch date'),('channels','channel')]:
        if not str(context.get(field,'')).strip():
            reason='Set the '+label+' in launch setup and revalidate.'
            global_reasons.append(reason)
            add('Launch setup',field,'CRITICAL',reason,'Launch Operations',[],field,'Whole launch')
    for reason in report.get('reconciliation_issues',[]):
        # Attribute gaps already have their own record-level corrections.
        if 'mandatory launch attribute gaps' in reason: continue
        global_reasons.append(reason)
        add('Release control',reason,'CRITICAL',reason,'Launch Operations',[],scope='Whole launch')
    # Deduplicate a repeated source finding while retaining distinct PO/SKU/location findings.
    actions=list({action_key(a):a for a in actions}.values())
    for line in lines: line['Issues']='; '.join(dict.fromkeys(line['Issues']))
    blocked=[r for r in lines if r['Status']=='Blocked']
    review=[r for r in lines if r['Status']=='Needs review']
    candidates=[r for r in lines if r['Status']=='Clear candidate']
    counts=dict(Counter(r['Status'] for r in lines))
    return {'version':VERSION,'actions':actions,'lines':lines,'counts':counts,
        'global_reasons':list(dict.fromkeys(global_reasons)),
        'critical_findings':sum(a['Severity']=='CRITICAL' for a in actions),
        'warning_findings':sum(a['Severity']=='WARNING' for a in actions),
        'commitment':money(lines),'blocked_commitment':money(blocked),
        'review_commitment':money(review),'candidate_commitment':money(candidates),
        'unmeasured_lines':sum(r['Commitment'] is None for r in lines),
        'release_policy':'Whole selected launch; any critical finding holds it. Clear candidates require a separately scoped, validated and approved launch before separate release.'}


def enrich_report(frames,payloads,report,context):
    operations=build_operations(frames,payloads,report,context)
    out=dict(report,operations=operations,actions=operations['actions'])
    affected=[r for r in operations['lines'] if r['Status']!='Clear candidate']
    if 'financial' in report:
        impact=money(affected)
        out['financial']=dict(report['financial'],affected_commitment_by_currency={c:impact.get(c,'0.00') for c in operations['commitment']})
    if 'financial_scenarios' in report:
        from orchestration.financial_scenarios import financial_scenarios
        out['financial_scenarios']=financial_scenarios(frames['po'],sell_through=context.get('sell_through_pct'),affected_line_ids={r['Line'] for r in affected})
    return out


def load_report(result):
    folder=Path(result['folder'])
    report=json.loads((folder/'reconciliation.json').read_text(encoding='utf-8'))
    if report.get('operations',{}).get('version')==VERSION: return report
    frames={}
    for kind in ('vendor','catalog','po'):
        source=folder/'evaluated_inputs'/(kind+'.csv')
        if source.exists(): frames[kind]=pd.read_csv(source,dtype=str,keep_default_na=False)
        else:
            source=folder/(kind+Path(result['files'][kind]).suffix)
            frames[kind]=pd.read_csv(source,dtype=str,keep_default_na=False) if source.suffix=='.csv' else pd.read_excel(source,dtype=str,keep_default_na=False)
    payloads={k:json.loads((folder/(k+'.json')).read_text(encoding='utf-8')) for k in frames}
    return enrich_report(frames,payloads,report,result.get('launch',{}).get('context',{}))


def decision_state(run,ops,legacy=False):
    if legacy: return 'Revalidation required','Validate this saved launch to apply the updated release checks.'
    if run['status'] in {'STALE','CYCLE_MISMATCH','AWAITING_AGENTS'}:
        return 'Revalidation required','Evidence is stale, incomplete or from different cycles. Validate the selected files again.'
    if ops['critical_findings'] or run['decision_detail']['status']=='BLOCKED':
        return 'Hold',f"{ops['critical_findings']} critical correction findings prevent approval. Resolve the corrections, then validate again."
    if run['status']=='REJECTED': return 'Hold','The reviewer held this launch. Review the recorded reason and revalidate after correction.'
    if run['status']=='COMPLETED': return 'Approved','This selected evidence version has a recorded human approval. No ERP order has been sent.'
    if ops['warning_findings']: return 'Review warnings',f"{ops['warning_findings']} warning findings require an explicit human review before approval."
    return 'Ready for human review','The selected launch passed the configured controls. A named reviewer must record the decision.'


def compare_runs(current, previous, older=()):
    now={action_key(a):a for a in current['actions']}; before={action_key(a):a for a in previous['actions']} if previous else {}
    historic=set().union(*({action_key(a) for a in p['actions']} for p in older)) if older else set()
    added=set(now)-set(before); reopened=added & historic
    result={'baseline':previous is None,'resolved':sorted(set(before)-set(now)),
        'new':sorted(added-reopened),'reopened':sorted(reopened),'remaining':sorted(set(now)&set(before))}
    rows=[]
    for label,key in [('Resolved','resolved'),('New','new'),('Reopened','reopened'),('Still open','remaining')]:
        for ident in result[key]:
            a=now.get(ident) or before[ident]
            rows.append({'Change':label,'Source':a['Source'],'Record':a['Identifier'],'Correction':a['Evidence required']})
    result['rows']=rows
    return result


def history_reports(result,runs):
    """Follow explicit predecessor links, never compare unrelated launches."""
    scope=result.get('review_scope_id',result['business_cycle_id']); index={}
    for p in Path(runs).glob('*/result.json'):
        try:
            r=json.loads(p.read_text(encoding='utf-8'))
            if (r.get('review_scope_id') or r.get('business_cycle_id'))==scope and r.get('run_id'):
                index[r['run_id']]=r
        except (OSError,ValueError):
            continue
    chain=[]; seen={result['run_id']}; previous=result.get('previous_run_id')
    while previous and previous in index and previous not in seen:
        seen.add(previous); r=index[previous]; chain.append((r,load_report(r))); previous=r.get('previous_run_id')
    return chain


def ranked_actions(state,ops,launch_date='',today=None):
    from orchestration.action_queue import queue_rows
    rows=queue_rows(state,launch_date,today)
    evidence={action_key(a):a for a in ops['actions']}
    for r in rows:
        a=evidence.get(r['Action ID'],{})
        r['Affected PO lines']=a.get('Affected lines',0)
        r['Affected commitment']=' · '.join(c+' '+v for c,v in a.get('Commitment by currency',{}).items()) or ('Unknown' if a.get('Unmeasured lines') else 'No linked PO value')
        r['Unmeasured lines']=a.get('Unmeasured lines',0)
        r['Responsible team']=state['actions'][r['Action ID']].get('assigned_team') or a.get('Owner','Launch Operations')
        record=state['actions'][r['Action ID']]
        r['Escalation owner']=record.get('escalation_owner') or 'Not assigned'
        r['Escalation']='Escalate overdue correction' if r['Timing']=='Overdue' else 'Assign owner / deadline' if r['Owner']=='Unassigned' or r['Deadline']=='Not set' else 'Monitor'
        r['Escalation note']=record.get('escalation_note','')
    # Currency totals are never compared across currencies. Ties prioritize downstream line count.
    return sorted(rows,key=lambda r:(r['Severity'] not in {'CRITICAL','BLOCKED'},r['Days remaining'] if r['Days remaining'] is not None else 100000,-r['Affected PO lines'],r['Source'],r['Record']))
