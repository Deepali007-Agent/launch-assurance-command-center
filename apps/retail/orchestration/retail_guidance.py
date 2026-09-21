"""Retail dependency policy for the local demonstration; no ERP execution."""
from collections import OrderedDict
import re
from html import unescape
from orchestration.reconciliation import normalize
from orchestration.decision_workflow import identity, line_id, money
from orchestration.cycle_history import action_key

POLICY='vendor-category-gender-1'

def dependency_findings(frames):
    vendors={identity(r.get('vendor_id')):r for r in normalize(frames['vendor']).to_dict('records')}
    items={identity(r.get('sku')):r for r in normalize(frames['catalog']).to_dict('records')}
    findings=[]
    for row in normalize(frames['po']).to_dict('records'):
        item=items.get(identity(row.get('sku')),{});vendor=vendors.get(identity(row.get('vendor_id')), {})
        category=str(row.get('category') or row.get('class') or '').strip()
        gender=str(row.get('gender') or '').strip()
        tests=[('category',bool(category),'Buying Operations','Supply the PO category.'),
               ('gender',bool(gender),'Buying Operations','Supply explicit PO gender; division is not used as a substitute.'),
               ('category_match',bool(category) and identity(category)==identity(item.get('category')),'Catalog Operations','Align the PO category with the linked item category.'),
               ('gender_match',bool(gender) and identity(gender)==identity(item.get('gender')),'Catalog Operations','Supply matching explicit gender on the item and PO.'),
               ('catalog_setup_status',identity(item.get('catalog_setup_status')) in {'ACTIVE','SET UP','SETUP COMPLETE'},'Catalog Operations','Complete item setup and supply catalog_setup_status = Active.'),
               ('finance_approval_status',identity(vendor.get('finance_approval_status'))=='APPROVED','Finance','Obtain Finance approval and supply finance_approval_status = Approved.')]
        for field,ok,team,correction in tests:
            if not ok:
                findings.append({'Source':'PO prerequisites','Identifier':line_id(row),'Severity':'CRITICAL','Owner':team,
                    'Evidence required':correction,'Missing fields':field,'SKU':identity(row.get('sku')),'Location':identity(row.get('location'))})
    return findings

def recommended_actions(rows,ops):
    evidence={action_key(a):a for a in ops['actions']};line_map={r['Line']:r for r in ops['lines']}
    groups=OrderedDict()
    for row in rows:
        a=evidence.get(row['Action ID'],{})
        category=a.get('Missing fields') or row['Correction']
        key=(row['Severity'],category,row['Responsible team'],row['Owner'],row['Deadline'])
        g=groups.setdefault(key,{'row':row,'lines':set(),'skus':set(),'count':0})
        g['count']+=1;g['lines'].update(a.get('Line IDs',[]))
        g['skus'].update(line_map[x]['SKU'] for x in a.get('Line IDs',[]) if x in line_map)
        if row['Source']=='Catalog':g['skus'].add(row['Record'])
    result=[]
    for number,((severity,category,team,owner,due),g) in enumerate(groups.items(),1):
        linked=[line_map[x] for x in g['lines'] if x in line_map]
        correction=g['row']['Correction']
        if correction in {'size','material','image_url','gender'}:correction='Complete '+correction.replace('_',' ')+' and revalidate the item file.'
        correction=unescape(re.sub(r'<[^>]+>','',correction))
        short=unescape(re.sub(r'<[^>]+>','',category)).replace('_',' ')
        for token,label in [('cancel date','Delivery dates'),('cost/retail/quantity','Order amounts'),('total quantity','Quantity'),('tax id','Vendor tax ID'),('contact email','Contact email'),('finance approval','Finance approval'),('catalog setup','Item setup')]:
            if token in short.lower():short=label;break
        if len(short)>35:short=g['row']['Source']+' checks'
        result.append({'No.':number,'Type':'Critical' if severity in {'CRITICAL','BLOCKED'} else 'Needs review',
            'Category':short,'SKUs impacted':len(g['skus']),'PO lines':len(linked),'Corrections':g['count'],
            'Recommended action':correction,'Team':team,'Owner':owner,'Due':due,
            'Measured commitment':' · '.join(c+' '+v for c,v in money(linked).items()) or 'Unknown / no linked value'})
    return result

def request_decisions(result,report):
    from pathlib import Path
    import pandas as pd
    folder=Path(result['folder'])/'evaluated_inputs'
    po=normalize(pd.read_csv(folder/'po.csv',dtype=str,keep_default_na=False))
    lookup={r['Line']:r for r in report['operations']['lines']}
    grouped=OrderedDict()
    for row in po.to_dict('records'):
        key=(identity(row.get('vendor_id')),str(row.get('category') or row.get('class') or 'Missing'),str(row.get('gender') or 'Missing'))
        g=grouped.setdefault(key,{'rows':[],'skus':set()})
        g['rows'].append(lookup[line_id(row)]);g['skus'].add(identity(row.get('sku')))
    enabled=result.get('launch',{}).get('context',{}).get('po_dependency_policy')==POLICY
    output=[]
    for (vendor,category,gender),g in grouped.items():
        ids={r['Line'] for r in g['rows']}
        actions=[a for a in report['operations']['actions'] if ids.intersection(a.get('Line IDs',[]))]
        critical=[a for a in actions if a['Severity']=='CRITICAL']
        status='Blocked' if critical else 'Review required' if actions else 'Prerequisites clear'
        if not enabled:status='Revalidate prerequisites'
        output.append({'Vendor':vendor,'Category':category,'Gender':gender,'SKUs':len(g['skus']),'PO lines':len(ids),
            'Prepare request':'Allowed as draft','Create executable PO':status,
            'Next step':'; '.join(dict.fromkeys(a['Evidence required'] for a in critical)) or ('Review warnings' if actions else 'Complete launch review; no ERP order is sent'),
            'Teams needed':', '.join(sorted({a['Owner'] for a in actions})) or 'Launch reviewer'})
    return output


def recommendations_by_team(recommendations):
    teams=['Catalog Operations','Buying Operations','Vendor Operations','Finance','Launch Operations']
    teams+=sorted({r['Team'] for r in recommendations}-set(teams))
    result={team:[] for team in teams}
    for row in recommendations:
        result[row['Team']].append(dict(row,**{'No.':len(result[row['Team']])+1}))
    return result
